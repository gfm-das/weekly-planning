// Writes the five presentation templates as showcase decks (slidev/showcase/<template>/slides.md) in English, the way
// "+ New Presentation" in the library makes them: node slidev/tools/make-mmm-showcase.mjs
// The showcase decks are what slidev/README.md ("Presentation templates") tells a person to copy into a server by hand,
// and slidev/tests/mmm-templates.test.mjs checks that they are exactly this output, so a change to a template is made in
// slidev/manager/templates and then written out again with this tool. The year-to-date chart needs a date: the
// showcase decks use the same fixed one (SHOWCASE_DATE) as the test.
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { buildTemplate, TEMPLATE_IDS } from '../manager/templates/index.mjs';

export const SHOWCASE_DATE = new Date(2026, 9, 12);
export const SHOWCASE_TITLES = { 'mmm-main': 'MMM MAIN', 'mmm-media': 'MMM Media', 'mmm-breakout': 'MMM Breakout rooms', zoko: 'ZOKO zone conference', stake: 'Stake coordination' };

export function showcaseDeck(id) {
  return buildTemplate(id, { title: SHOWCASE_TITLES[id], lang: 'en', now: SHOWCASE_DATE });
}

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  const root = path.join(path.dirname(fileURLToPath(import.meta.url)), '..', 'showcase');
  for (const id of TEMPLATE_IDS.filter(x => x !== 'blank')) {
    fs.mkdirSync(path.join(root, id), { recursive: true });
    // Unix line endings: the deck is copied into a Linux container.
    fs.writeFileSync(path.join(root, id, 'slides.md'), showcaseDeck(id));
    console.log(`slidev/showcase/${id}/slides.md`);
  }
}
