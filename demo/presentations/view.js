// The viewer: one slide at a time, arrows and keys, a counter, swipe, a full screen button.
import decks from './decks.js';
import { mount } from './render.js';

const params = new URLSearchParams(location.search);
const deck = decks[params.get('deck')] || decks['mmm-main'];
const $ = id => document.getElementById(id);
const total = deck.slides.length;
let index = Math.min(total, Math.max(1, parseInt(location.hash.slice(1), 10) || 1)) - 1;
let shown = null;

document.title = deck.name + ' · Presentations';
$('title').textContent = deck.name;
$('dots').innerHTML = deck.slides.map((_, i) => `<button type="button" aria-label="Slide ${i + 1}" data-i="${i}"></button>`).join('');

function show(i) {
  index = Math.min(total - 1, Math.max(0, i));
  if (shown) shown.destroy();
  shown = mount($('host'), deck.slides[index]);
  $('count').textContent = `${index + 1} / ${total}`;
  $('prev').disabled = index === 0;
  $('next').disabled = index === total - 1;
  $('dots').querySelectorAll('button').forEach((b, n) => b.setAttribute('aria-current', String(n === index)));
  try { history.replaceState(null, '', `#${index + 1}`); } catch (e) {}
}

$('prev').addEventListener('click', () => show(index - 1));
$('next').addEventListener('click', () => show(index + 1));
$('dots').addEventListener('click', e => { const b = e.target.closest('button[data-i]'); if (b) show(Number(b.dataset.i)); });

const wrap = $('wrap');
function inFull() { return document.fullscreenElement === wrap || wrap.classList.contains('pseudo-fs'); }
function setFull(on) {
  document.body.classList.toggle('fs', on);
  $('fs').textContent = on ? 'Exit full screen' : 'Full screen';
  setTimeout(() => shown && shown.redraw(), 60);
}
async function toggleFull() {
  if (inFull()) {
    wrap.classList.remove('pseudo-fs');
    if (document.fullscreenElement) { try { await document.exitFullscreen(); } catch (e) {} }
    setFull(false);
    return;
  }
  try { await wrap.requestFullscreen(); } catch (e) { wrap.classList.add('pseudo-fs'); setFull(true); } // a frame without the permission: fill the window instead
}
$('fs').addEventListener('click', toggleFull);
document.addEventListener('fullscreenchange', () => { if (!document.fullscreenElement) wrap.classList.remove('pseudo-fs'); setFull(!!document.fullscreenElement); });

document.addEventListener('keydown', e => {
  if (e.ctrlKey || e.metaKey || e.altKey) return;
  const k = e.key;
  if (k === 'ArrowRight' || k === 'ArrowDown' || k === 'PageDown' || k === ' ') { show(index + 1); e.preventDefault(); }
  else if (k === 'ArrowLeft' || k === 'ArrowUp' || k === 'PageUp') { show(index - 1); e.preventDefault(); }
  else if (k === 'Home') show(0);
  else if (k === 'End') show(total - 1);
  else if (k === 'f' || k === 'F') toggleFull();
  else if (k === 'Escape' && wrap.classList.contains('pseudo-fs')) toggleFull();
});

// Swipe on a phone.
let x0 = null;
$('stage').addEventListener('touchstart', e => { x0 = e.touches[0].clientX; }, { passive: true });
$('stage').addEventListener('touchend', e => {
  if (x0 === null) return;
  const dx = e.changedTouches[0].clientX - x0; x0 = null;
  if (Math.abs(dx) > 40) show(index + (dx < 0 ? 1 : -1));
}, { passive: true });

// The charts are drawn for the slide's size: draw them again when it changes.
let timer = 0;
new ResizeObserver(() => { clearTimeout(timer); timer = setTimeout(() => shown && shown.redraw(), 80); }).observe($('stage'));
show(index);
addEventListener('hashchange', () => { const n = parseInt(location.hash.slice(1), 10); if (n && n - 1 !== index) show(n - 1); });
