// Mission Dashboard: inside the portal (the Dashboards button), follow the portal's light or dark theme.
// The shell sends {type: 'portal-theme', theme} when the frame loads and whenever the theme changes
// ('dark', 'light' or 'mission', which is light), and answers {type: 'portal-theme-request'}, which this
// sends once it listens (the load event may come first). Opened on its own, the deck follows the
// computer's setting (colorSchema: auto), and D switches.
// It also marks the page for the phone note in style.css: gfm-in-frame (inside the portal, whose menu
// keeps its width on a phone held sideways, so turning the phone alone hardly helps) and
// gfm-can-fullscreen (this browser can show the deck full screen with Slidev's full-screen button;
// iPhones cannot).
import { defineAppSetup } from '@slidev/types'
import { useDarkMode } from '@slidev/client'

export default defineAppSetup(() => {
  if (typeof window === 'undefined')
    return
  const doc = document as Document & { webkitFullscreenEnabled?: boolean }
  const root = document.documentElement
  root.classList.toggle('gfm-can-fullscreen', !!(doc.fullscreenEnabled || doc.webkitFullscreenEnabled))
  if (window.parent === window)
    return
  root.classList.add('gfm-in-frame')
  const { isDark } = useDarkMode()
  window.addEventListener('message', (event) => {
    if (event.source !== window.parent)
      return
    const data = event.data || {}
    if (data.type === 'portal-theme' && typeof data.theme === 'string')
      isDark.value = data.theme === 'dark'
  })
  try {
    window.parent.postMessage({ type: 'portal-theme-request' }, '*')
  }
  catch {}
})
