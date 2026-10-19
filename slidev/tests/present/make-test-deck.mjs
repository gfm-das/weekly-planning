// TEST ONLY: writes the deck edge_present.ps1 checks (11 slides, a sample chart on each after the title; no live
// numbers, so it builds and prints without portal-api). The product ships no decks, so the test makes its own.
//   node make-test-deck.mjs <folder>   -> <folder>/slides.md
import fs from 'node:fs';
import path from 'node:path';

const chart = i => `<MissionChart type="${['bar', 'line', 'pie'][i % 3]}" title="Sample ${i}" :height="320" csv="Week,North,South; W1,${i},${i + 2}; W2,${i + 3},${i + 1}; W3,${i + 5},${i + 4}" />`;
export const testDeck = () => `---\ntitle: Test deck\ntheme: default\n---\n\n# Test deck\n`
  + Array.from({ length: 10 }, (_, i) => `\n---\n\n# Slide ${i + 2}\n\n${chart(i + 1)}\n`).join('');

const out = process.argv[2];
if (out) {
  fs.mkdirSync(out, { recursive: true });
  fs.writeFileSync(path.join(out, 'slides.md'), testDeck());
  console.log(path.join(out, 'slides.md'));
}
