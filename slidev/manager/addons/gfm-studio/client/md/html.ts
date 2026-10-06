/**
 * Editing the text inside raw HTML, without disturbing the HTML.
 *
 * A deck written by hand is full of markup Markdown has no syntax for: a
 * paragraph carrying utility classes, a grid of divs, a span holding one styled
 * word. Studio refused all of it, because writing such a block back through the
 * Markdown serialiser would return the text and drop the tag and its attributes
 * with it. That is the right instinct and the wrong conclusion: the words can be
 * replaced where they sit, and everything around them left exactly as it was.
 *
 * The element is found by the text it currently holds rather than by counting
 * tags, because that is the one thing the rendered page and the source agree on
 * without a parser. If the same words appear twice in the block there is no way
 * to tell which was meant, so nothing is written.
 */

/** Whitespace differs between source and DOM; meaning does not. */
function collapse(text: string): string {
  return text.replace(/\s+/g, ' ').trim()
}

/**
 * The words an element shows, with the markup between them taken out.
 *
 * The element is found by its text because that is what the source and the
 * rendered page agree on: the source may say `Helt <b>vanlig</b> tekst`, the
 * page reports `Helt vanlig tekst`, and comparing the two as written would
 * never match anything containing inline markup.
 */
function textOf(html: string): string {
  return collapse(stripStudioAttrs(html).replace(/<[^>]*>/g, ''))
}

/** The annotations Studio adds to the rendered page are not part of the deck. */
export function stripStudioAttrs(html: string): string {
  return html.replace(/\s+data-studio-[\w-]+="[^"]*"/g, '')
}

interface Span {
  /** Where the element's inner content starts and ends in the block. */
  from: number
  to: number
}

/**
 * Every `<tag …>…</tag>` in a block, at the top level of that tag.
 *
 * A tag nested inside another of the same name makes "the closing tag"
 * ambiguous to a scan this simple, so such a block is refused rather than
 * guessed at.
 */
function spansOf(block: string, tag: string): Span[] | null {
  const open = new RegExp(`<${tag}\\b[^>]*?>`, 'gi')
  const close = new RegExp(`</${tag}\\s*>`, 'gi')
  const opens = [...block.matchAll(open)]
  const closes = [...block.matchAll(close)]
  if (!opens.length || opens.length !== closes.length)
    return null

  const spans: Span[] = []
  for (let i = 0; i < opens.length; i++) {
    const from = opens[i].index! + opens[i][0].length
    const to = closes[i].index!
    // Interleaved rather than nested is what this can read; anything else is
    // a shape it would have to parse properly to be sure about.
    if (to < from)
      return null
    if (i + 1 < opens.length && opens[i + 1].index! < to)
      return null
    spans.push({ from, to })
  }
  return spans
}

/**
 * Replaces the words inside one element of a block.
 *
 * `current` is what the element holds now, used to find it. `next` is HTML,
 * not Markdown: the block is raw HTML, and Markdown written inside one is not
 * processed, so what goes back in has to be what the browser will render.
 *
 * Returns null when the element cannot be found exactly once, which leaves the
 * caller to fall back to editing the block as text.
 */
export function replaceInnerHtml(
  block: string,
  tag: string,
  current: string,
  next: string,
): string | null {
  const spans = spansOf(block, tag.toLowerCase())
  if (!spans)
    return null

  const wanted = collapse(current)
  const found = spans.filter(span => textOf(block.slice(span.from, span.to)) === wanted)
  if (found.length !== 1)
    return null

  const { from, to } = found[0]
  return block.slice(0, from) + next + block.slice(to)
}
