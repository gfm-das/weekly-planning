// Slidev's preparser hook of the GFM addon: changes to a deck's slides before Slidev reads them.
import { deckFolderPreparser } from '../lib/deck-folder.mjs'
import { publishedDeckPreparser } from '../lib/published-deck.mjs'

// Every deck includes files only from its own folder, in the editor and in
// builds (lib/deck-folder.mjs; zone presentations, round 7). Published decks
// also get Slidev's browser exporter (/p/<deck>/export: PDF), which Slidev
// otherwise offers only in the editor. Build only; see lib/published-deck.mjs.
export default (options: { mode?: string } = {}) => [...deckFolderPreparser(), ...publishedDeckPreparser(options)]
