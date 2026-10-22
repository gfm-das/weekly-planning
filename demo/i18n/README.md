# Interface translation (14 languages)

`portal/i18n.js` translates every page of the portal, DA Management and Presentations from the catalogs in this
folder. The full description, the deploy steps and the term list are in `docs/handoff/round6/i18n.md`.

- `en.json`: the English interface texts, one key each (`"planning.title": "Weekly Planning"`). A text may hold
  `{placeholders}`; `{n}`, `{count}`, `{number}` and `{total}` match only numbers. A plural is
  `{"one": "…", "other": "…"}` (with `few`/`many` where the language has them).
- `<code>.json`: the same keys in German (de), Spanish (es), French (fr), Portuguese (pt), Ukrainian (uk), Russian (ru),
  Italian (it), Turkish (tr), Persian (fa), Romanian (ro), Swedish (sv), Danish (da) and Arabic (ar). **Every catalog
  except English needs review by a native speaker.**
- `catalogs.json`: the list of languages with their own names, the Church's language code and the direction.
- `rtl.css`: layout fixes for Persian and Arabic (`dir="rtl"`), loaded by i18n.js only for them.

How it works: i18n.js replaces a text node or attribute (placeholder, title, aria-label, alt) whose text equals an
English catalog text by the same key in the chosen language, also in content added later. Written content never
changes: inputs, textareas, `[data-i18n-ignore]`, `[translate="no"]`, names, notes and places. Explicit keys still
work: `data-i18n="calendar.title"`, `data-i18n-placeholder`, `data-i18n-title`, `data-i18n-aria-label`.

The language comes from `?lang=` (ISO or Church code), then the portal's choice for the tab
(`sessionStorage.mission_language`, the `mission-language` message from the shell), then the `gfm_lang` cookie shared
with DA Management and Presentations, then English. The shell's list shows the languages assigned to the person in
DA Management (primary and additional), each in its own name. The language layer grants no role or access.

A page loads it in `<head>`: `<script src="i18n.js?v=6"></script>` (DA Management and Presentations load the portal's
copy). `MissionI18n.t(key, values)`, `.number()`, `.date()`, `.churchUrl(url)`, `.withLanguage(url[, param])`,
`.untranslated()`, `.ready` and the `mission-i18n-change` event are there for page code.

A new page: `node portal/tests/i18n-missing.cjs <file>` lists its texts that are not in `en.json`;
`node portal/tests/i18n-keys.cjs add <prefix> <file>` adds them, `todo <lang>` prints what a language still needs and
`merge <lang> <file>` merges translations. Then add the file to `PAGES` in `portal/tests/i18n-missing.cjs` and run
`node portal/tests/i18n-check.cjs`.
