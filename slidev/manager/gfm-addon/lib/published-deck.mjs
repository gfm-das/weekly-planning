// Published decks (slidev build) get Slidev's browser exporter, the page
// /p/<deck>/export with "PDF" (the browser's print dialog, "Save as PDF").
// Slidev offers it only in the editor by default (browserExporter: 'dev'),
// which is why downloading worked only in editor mode. A deck that sets
// browserExporter itself keeps its choice. Only the build is changed: the
// editor already has the exporter, and Studio must never write this setting
// back into slides.md.
export function publishedDeckPreparser({ mode } = {}) {
  if (mode !== 'build') return []
  let first = true
  return [{
    name: 'gfm-addon:browser-exporter',
    // The entry file is parsed first and its first slide carries the
    // headmatter, so the first slide seen here is the headmatter.
    transformSlide(_content, frontmatter) {
      if (!first) return undefined
      first = false
      if (frontmatter && typeof frontmatter === 'object' && !Object.hasOwn(frontmatter, 'browserExporter'))
        frontmatter.browserExporter = true
      return undefined
    },
  }]
}
