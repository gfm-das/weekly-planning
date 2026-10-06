/**
 * GFM Studio: bringing a whole presentation (or a few slides) into the deck, and checking one first.
 *
 * Written for `Paste Presentation` (gfm/ImportDialog.vue): a person pastes the Slidev Markdown an AI wrote. Three ways in:
 *   replace  the pasted deck becomes the deck (the deck keeps its own title, and the settings the paste leaves out)
 *   append   the pasted slides go after the last slide
 *   insert   the pasted slides go after a given slide
 * The pasted deck's own settings (theme, fonts ...) are never added to a deck that is not replaced: only the settings that
 * belong to a slide (its layout, class, background ...) travel with the first pasted slide.
 * `restore` writes a whole file back; Studio's Undo and Redo of an import use it, so a big import is one undoable action.
 * `check` reads the Markdown with Slidev's own parser, so "valid" means Slidev can load it.
 */
import { readFile, writeFile } from 'node:fs/promises'
import { parseSync } from '@slidev/parser'
import YAML from 'yaml'
import type { ResolvedSlidevOptions } from '@slidev/types'
import { joinDeck, prettifyRaw, splitDeck } from './slide-source.ts'

export const MAX_IMPORT_BYTES = 1_500_000
export const MAX_IMPORT_SLIDES = 300

/** Settings of the whole deck: they stay out of slides that are added to an existing deck. */
export const DECK_ONLY_KEYS = new Set([
  'theme', 'title', 'titleTemplate', 'info', 'author', 'keywords', 'fonts', 'themeConfig', 'defaults', 'drawings', 'colorSchema',
  'aspectRatio', 'canvasWidth', 'highlighter', 'lineNumbers', 'monaco', 'download', 'exportFilename', 'export', 'presenter',
  'browserExporter', 'remoteAssets', 'selectable', 'record', 'contextMenu', 'wakeLock', 'seoMeta', 'htmlAttrs', 'favicon', 'mdc',
  'addons', 'css', 'twoslash', 'duration', 'timer', 'routerMode', 'preload', 'studio',
])

export type ImportAction =
  | { action: 'import', mode: 'replace' | 'append' | 'insert', after?: number, markdown: string }
  | { action: 'restore', markdown: string }

const normalize = (text: string) => String(text).replace(/\r\n?/g, '\n').replace(/^﻿/, '')

function frontmatterOf(raw: string): { yaml: string, body: string } | null {
  const lines = raw.split('\n')
  if (lines[0]?.trimEnd() !== '---')
    return null
  const end = lines.findIndex((line, i) => i > 0 && line.trimEnd() === '---')
  if (end < 0)
    return null
  return { yaml: lines.slice(1, end).join('\n'), body: lines.slice(end + 1).join('\n') }
}

/** Parses a frontmatter block; text that is not a mapping gives {}. */
function readYaml(text: string): Record<string, any> {
  try {
    const value = YAML.parse(text)
    return value && typeof value === 'object' && !Array.isArray(value) ? value : {}
  }
  catch {
    return {}
  }
}

/** The pasted deck's first slide, made a slide of its own: its deck-wide settings are dropped (they were the headmatter). */
function asSlide(raw: string): string {
  const fm = frontmatterOf(raw)
  if (!fm)
    return raw.replace(/^\n+/, '')
  const kept = Object.fromEntries(Object.entries(readYaml(fm.yaml)).filter(([key]) => !DECK_ONLY_KEYS.has(key)))
  return prettifyRaw(Object.keys(kept).length ? YAML.stringify(kept).trim() : undefined, fm.body)
}

function slideRaws(markdown: string): string[] {
  return splitDeck(normalize(markdown)).slides.map(s => s.raw)
}

function assertSize(markdown: string) {
  if (typeof markdown !== 'string' || !markdown.trim())
    throw new Error('There is nothing to import: paste the presentation first.')
  if (Buffer.byteLength(markdown) > MAX_IMPORT_BYTES)
    throw new Error('This is too large to import (over 1.5 MB of text).')
}

/** The deck's file as Slidev has it (the entry file; an imported deck is always one file). */
async function entryFile(options: ResolvedSlidevOptions) {
  const filepath = options.data.entry.filepath
  return { filepath, raw: await readFile(filepath, 'utf-8') }
}

/**
 * Applies an import or a restore. Answers { ok, no (the first imported slide), total, count, before, after }:
 * `before` and `after` are the whole file, which Studio keeps so Undo and Redo can write them back.
 */
export async function applyImport(options: ResolvedSlidevOptions, payload: ImportAction) {
  const { filepath, raw } = await entryFile(options)
  if (payload.action === 'restore') {
    if (typeof payload.markdown !== 'string')
      throw new Error('Nothing to restore.')
    await writeFile(filepath, payload.markdown, 'utf-8')
    return { ok: true, no: 1, total: splitDeck(payload.markdown).slides.length, count: 0, before: raw, after: payload.markdown }
  }

  assertSize(payload.markdown)
  const incoming = slideRaws(payload.markdown)
  if (incoming.length > MAX_IMPORT_SLIDES)
    throw new Error(`A presentation can have up to ${MAX_IMPORT_SLIDES} slides.`)
  const existing = splitDeck(raw).slides.map(s => s.raw)

  let output: string
  let no = 1
  if (payload.mode === 'replace') {
    // The pasted settings win, except the deck's own title (renaming is a separate act) and the deck-wide settings the
    // paste leaves out.
    const old = frontmatterOf(existing[0] ?? '')
    const head = frontmatterOf(incoming[0] ?? '')
    const oldKeys = readYaml(old?.yaml ?? '')
    const newKeys = readYaml(head?.yaml ?? '')
    const merged: Record<string, any> = { ...Object.fromEntries(Object.entries(oldKeys).filter(([k]) => DECK_ONLY_KEYS.has(k))), ...newKeys }
    if (oldKeys.title !== undefined)
      merged.title = oldKeys.title
    const body = head ? head.body : incoming[0]
    const first = `---\n${YAML.stringify(merged).trim()}\n---\n${body}`.replace(/\n{3,}/g, '\n\n')
    output = joinDeck([first, ...incoming.slice(1)])
  }
  else {
    const slides = incoming.map((s, i) => (i === 0 ? asSlide(s) : s))
    const total = existing.length
    const after = payload.mode === 'append' ? total : Math.min(Math.max(1, Math.round(Number(payload.after) || total)), total)
    no = after + 1
    output = joinDeck([...existing.slice(0, after), ...slides, ...existing.slice(after)])
  }
  await writeFile(filepath, output, 'utf-8')
  return { ok: true, no, total: splitDeck(output).slides.length, count: incoming.length, before: raw, after: output }
}

/**
 * Reads Markdown with Slidev's parser, without touching the deck. Answers { ok, slides, errors: [{ slide, message }] }:
 * `ok` means Slidev can load it (its settings are valid YAML, every block closes).
 */
export function checkMarkdown(markdown: string) {
  if (typeof markdown !== 'string' || !markdown.trim())
    return { ok: false, slides: 0, errors: [{ slide: 0, message: 'There is nothing to check.' }] }
  if (Buffer.byteLength(markdown) > MAX_IMPORT_BYTES)
    return { ok: false, slides: 0, errors: [{ slide: 0, message: 'This is too large (over 1.5 MB of text).' }] }
  const errors: { slide: number, message: string }[] = []
  let slides = 0
  try {
    const data = parseSync(normalize(markdown), 'import.md')
    slides = data.slides.length
    data.slides.forEach((slide: any, i: number) => {
      for (const error of slide.frontmatterDoc?.errors ?? [])
        errors.push({ slide: i + 1, message: String(error.message ?? error).split('\n')[0] })
    })
  }
  catch (error: any) {
    errors.push({ slide: 0, message: String(error?.message ?? error).split('\n')[0] })
  }
  return { ok: errors.length === 0, slides, errors }
}
