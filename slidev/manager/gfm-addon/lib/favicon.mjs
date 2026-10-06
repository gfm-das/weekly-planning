// The tab icon for decks, the editor and the library: a small teal chart,
// written into the page itself so no icon is fetched from the internet
// (Slidev's default comes from cdn.jsdelivr.net). Used by
// setup/vite-plugins.ts (built decks) and by the manager (editor pages).

/** Slidev's default `favicon` (its headmatter default); only this one is replaced. */
export const SLIDEV_DEFAULT_FAVICON = 'https://cdn.jsdelivr.net/gh/slidevjs/slidev/assets/favicon.png'

const SVG = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64">'
  + '<rect width="64" height="64" rx="14" fill="#087f8c"/>'
  + '<rect x="14" y="34" width="9" height="16" rx="2" fill="#fff"/>'
  + '<rect x="27.5" y="24" width="9" height="26" rx="2" fill="#fff"/>'
  + '<rect x="41" y="14" width="9" height="36" rx="2" fill="#fff"/>'
  + '</svg>'

/** A data: URL, safe inside any HTML attribute (every quote and bracket is encoded). */
export const FAVICON_DATA_URL = `data:image/svg+xml,${encodeURIComponent(SVG)}`

/** Replaces Slidev's default icon link in an HTML page; other icons stay. */
export function localFavicon(html) {
  return String(html).split(SLIDEV_DEFAULT_FAVICON).join(FAVICON_DATA_URL)
}
