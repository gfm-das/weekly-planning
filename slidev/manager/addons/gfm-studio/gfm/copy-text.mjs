// GFM Studio: copy a text to the clipboard, also where the browser has no clipboard API.
//
// navigator.clipboard only exists on https or localhost ("secure contexts"). The portal on the mission's own network is
// plain http, so there it is missing and Copy did nothing. Then the old way is used: the text goes into a hidden text
// box, is selected and copied with document.execCommand('copy'), which browsers still allow after a click.
// Returns true when the text was copied; false when neither way worked (the caller then shows the text, selected, so
// the person can press Ctrl+C). Used by ImportDialog.vue (Paste Presentation: Copy AI instructions).

/** @param {string} text @param {{ win?: any, doc?: any }} [env] */
export async function copyText(text, env = {}) {
  const win = env.win ?? (typeof window !== 'undefined' ? window : undefined)
  const doc = env.doc ?? (typeof document !== 'undefined' ? document : undefined)
  const value = String(text ?? '')
  const api = win?.navigator?.clipboard
  if (api && typeof api.writeText === 'function' && win.isSecureContext !== false) {
    try { await api.writeText(value); return true } catch {}
  }
  if (!doc?.body || typeof doc.execCommand !== 'function') return false
  const box = doc.createElement('textarea')
  box.value = value
  box.setAttribute('readonly', '')
  box.style.position = 'fixed'
  box.style.top = '0'
  box.style.left = '0'
  box.style.opacity = '0'
  const before = doc.activeElement
  doc.body.appendChild(box)
  let ok = false
  try { box.select(); ok = doc.execCommand('copy') === true } catch { ok = false }
  box.remove()
  try { before?.focus?.() } catch {}
  return ok
}

/** The dialog's words for the copy part, in the reader's language when the editor page sent them (labels). */
export const COPY_WORDS = {
  copy: 'Copy AI instructions',
  copied: 'AI instructions copied. Paste them into ChatGPT or Claude.',
  steps: 'Step 1: copy the instructions and give them to ChatGPT or Claude with your topic. Step 2: paste what it writes below.',
  show: 'Show instructions',
  hide: 'Hide instructions',
  blocked: 'This browser blocked copying. The instructions are selected below: press Ctrl+C (⌘C on a Mac).',
}

/** Only known keys, only short strings: the labels come in a message from the editor page. */
export function copyWords(labels) {
  const out = { ...COPY_WORDS }
  if (labels && typeof labels === 'object') {
    for (const k of Object.keys(COPY_WORDS)) {
      const v = labels[k]
      if (typeof v === 'string' && v.trim() && v.length <= 400) out[k] = v
    }
  }
  return out
}
