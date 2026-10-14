// Round 13: the "Exit full screen" button sits in a corner, fades after about 2 s, comes back on mouse move or tap,
// and Esc still exits. Runs the real auto-hide helper from portal-enhancements.js (between AUTOHIDE-START and
// AUTOHIDE-END) with a fake clock, and reads the shell code and portal.css as text.
// Run: node portal/tests/exit-fullscreen-check.cjs
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

const read = name => fs.readFileSync(path.join(__dirname, '..', name), 'utf8');
const source = read('portal-enhancements.js').replace(/\r\n/g, '\n');
const css = read('portal.css').replace(/\r\n/g, '\n');
let passed = 0;
const ok = (value, message) => { assert.ok(value, message); passed++; };
const eq = (a, b, message) => { assert.deepEqual(a, b, message); passed++; };

// ---- The helper, with a fake clock ---------------------------------------------------------------------------------
const block = source.match(/\/\/ AUTOHIDE-START\n([\s\S]*?)\/\/ AUTOHIDE-END/);
ok(block, 'portal-enhancements.js has the auto-hide helper');
const createAutoHider = new Function(`${block[1]}; return createAutoHider;`)();

function clock() {
  let now = 0, next = 1;
  const timers = new Map();
  return {
    setTimer: (fn, ms) => { const id = next++; timers.set(id, { at: now + ms, fn }); return id; },
    clearTimer: id => timers.delete(id),
    advance(ms) {
      const end = now + ms;
      for (;;) {
        const due = [...timers].filter(([, t]) => t.at <= end).sort((a, b) => a[1].at - b[1].at)[0];
        if (!due) break;
        timers.delete(due[0]);
        now = due[1].at;
        due[1].fn();
      }
      now = end;
    },
  };
}
function hider() {
  const c = clock();
  const log = [];
  const h = createAutoHider(() => log.push('show'), () => log.push('hide'), 2000, c.setTimer, c.clearTimer);
  return { h, c, log };
}

{
  const { h, c, log } = hider();
  h.poke();
  eq(log, [], 'nothing happens while not in full screen');
  h.start();
  eq(log, ['show'], 'the button shows when full screen starts');
  c.advance(1900);
  eq(log, ['show'], 'it is still there just before 2 s');
  c.advance(200);
  eq(log, ['show', 'hide'], 'it fades after about 2 s');
  h.poke();
  eq(log, ['show', 'hide', 'show'], 'a mouse move or tap brings it back');
  c.advance(1500);
  h.poke();
  c.advance(1500);
  eq(log.at(-1), 'show', 'moving again keeps it for another 2 s from the last move');
  c.advance(600);
  eq(log.at(-1), 'hide', '... then it fades again');
  const before = log.length;
  h.poke(); h.poke(); h.poke();
  eq(log.length, before + 1, 'many mouse moves show it once');
}
{
  const { h, c, log } = hider();
  h.start();
  h.hold(true);
  c.advance(10000);
  eq(log, ['show'], 'it stays while the pointer or the keyboard focus is on it');
  h.hold(false);
  c.advance(2100);
  eq(log, ['show', 'hide'], 'it fades 2 s after the pointer or focus leaves');
  h.hold(true);
  eq(log.at(-1), 'show', 'focusing a faded button shows it');
}
{
  const { h, c, log } = hider();
  h.start();
  h.stop();
  c.advance(5000);
  eq(log, ['show'], 'leaving full screen cancels the timer');
  h.poke();
  eq(log, ['show'], 'moves outside full screen do nothing');
  h.start();
  eq(log, ['show', 'show'], 'the next full screen shows the button again');
}

// ---- The shell code ---------------------------------------------------------------------------------------------------
ok(/exitFullScreen\.textContent = 'Exit full screen'/.test(source), 'the button keeps its English text (the catalogs translate it)');
ok(/classList\.add\('faded'\)/.test(source) && /\b2000\b/.test(source), 'the shell fades the button after 2000 ms');
ok(/for \(const type of \['pointermove', 'pointerdown', 'mousemove', 'touchstart', 'click'\]\) exitZone\.addEventListener/.test(source), 'the corner area reacts to mouse move and tap');
ok(/for \(const type of \['mousemove', 'touchstart', 'pointerdown', 'keydown'\]\) document\.addEventListener\(type, pokeExit/.test(source), 'mouse, touch and keys on the shell bring the button back');
ok(/inner\.addEventListener\(type, pokeExit/.test(source), 'pages of the portal itself (same address) bring it back too');
ok(/event\.key === 'Escape' && frameBox\.classList\?\.contains\('frame-expanded'\)/.test(source), 'Esc still leaves the expanded view (the browser handles Esc in its own full screen)');
ok(/function showExit\(on\)/.test(source) && /showExit\(frameIsFullScreen\(\)\)/.test(source) && /showExit\(on\);/.test(source), 'the button follows both kinds of full screen');
ok(/exitFullScreen\.hidden = !on/.test(source) && !/exitFullScreen\.hidden = !frameIsFullScreen/.test(source), 'no older code shows the button without the auto-hide');

// ---- portal.css -------------------------------------------------------------------------------------------------------
const rule = selector => (css.match(new RegExp(selector.replace(/[.*+?^${}()|[\]\\]/g, '\\$&') + ' \\{([^}]*)\\}')) || [])[1] || '';
ok(/inset-inline-end/.test(rule('.frame-exit-fullscreen')) && /bottom:/.test(rule('.frame-exit-fullscreen')) && !/\btop:/.test(rule('.frame-exit-fullscreen')), 'css: the button is in the bottom corner (round 14: never over the top-right links), on the end side');
ok(/opacity 0\.4s/.test(rule('.frame-exit-fullscreen')), 'css: the fade is animated');
ok(/opacity: 0/.test(rule('.frame-exit-fullscreen.faded')) && /pointer-events: none/.test(rule('.frame-exit-fullscreen.faded')), 'css: a faded button is invisible and does not catch clicks');
ok(/pointer-events: none/.test(rule('.frame-exit-fullscreen:not(.faded) ~ .frame-exit-zone')), 'css: while the button shows, the corner area lets clicks through');
ok(/transition: none/.test(css.slice(css.indexOf('prefers-reduced-motion', css.indexOf('.frame-exit-zone')))), 'css: no animation for people who ask for less motion');
const phone = css.slice(css.indexOf('@media (max-width: 780px) {\n  .frame-exit-fullscreen'));
ok(/min-height: 44px/.test(phone.slice(0, 400)), 'css: a 44 px button on phones');
ok(!/frame-exit-fullscreen[^{]*\{[^}]*\bright:/.test(css), 'css: no left-to-right-only "right:" on the button');

console.log(`exit full screen: ${passed} checks passed (corner, fades after 2 s, returns on move or tap, stays while used, Esc, phone)`);
