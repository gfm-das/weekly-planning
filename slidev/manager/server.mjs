// The presentation manager: start here.
//
// What it is: the one program behind Presentations (npm start runs it: node /slidev/manager/server.mjs). It keeps
// the decks in /slidev/decks, publishes them with Slidev, starts Slidev's editor for a deck being edited, and
// checks for every request who is asking and what they may do (portal-api decides).
// It listens on two addresses, on purpose:
//   - the manager address (browsers use port 3030): the library, the editor page /studio, the API and the
//     portal Whiteboard's chart frames. The Presentations sign-in works here. -> manager-routes.mjs
//   - the deck address (browsers use port 8089): published decks and the deck editor, which run the deck's own
//     page code. Only a deck pass for that one deck works here, never the sign-in. -> deck-routes.mjs
//     (deck-origin.mjs explains why there are two addresses.)
// Who uses it: the Slidev container (slidev-compose.yml); the tests start a copy of it.
// How it fits: this file only starts the two listeners and two jobs that run after the start. The README next to
// it (manager/README.md) is a map of every file.
import http from 'node:http';
import { ADDON_FINGERPRINT, rebuildDecksWithOldAddon } from './builds.mjs';
import { handleDeckRequest, handleDeckSocket } from './deck-routes.mjs';
import { prestartRecentDeck } from './editors.mjs';
import { handleManagerRequest } from './manager-routes.mjs';
import { ADDON_REBUILD, ADDON_REBUILD_DELAY_MS, BIND_ADDRESS, BUILD_CONCURRENCY, DECK_PUBLIC_PORT, DECK_SERVER_PORT, MANAGER_PORT, NICE_BIN } from './settings.mjs';

// ---- the manager address ----

const managerServer = http.createServer(handleManagerRequest);
// The editor's live connection (a websocket) goes to the deck address since round 8; the manager address has none.
managerServer.on('upgrade', (req, socket) => socket.destroy());
managerServer.listen(MANAGER_PORT, BIND_ADDRESS, () => {
  console.log(`Presentation Manager listening on port ${MANAGER_PORT} (chart addon ${ADDON_FINGERPRINT}, ${BUILD_CONCURRENCY} build${BUILD_CONCURRENCY > 1 ? 's' : ''} at a time${NICE_BIN ? '' : ', builds without nice'})`);
  // The next editor to open is most likely the deck changed last.
  prestartRecentDeck('the manager started').catch(error => console.error('[prestart]', error.message));
  // After a deploy of a new chart addon, published decks get the new chart code by themselves.
  if (ADDON_REBUILD) setTimeout(() => rebuildDecksWithOldAddon().catch(error => console.error('[addon] rebuild check failed', error.message)), ADDON_REBUILD_DELAY_MS).unref();
});

// ---- the deck address ----

const deckServer = http.createServer(handleDeckRequest);
deckServer.on('upgrade', handleDeckSocket);
deckServer.listen(DECK_SERVER_PORT, BIND_ADDRESS, () => {
  console.log(`Deck address listening on port ${deckServer.address().port} (browsers use port ${DECK_PUBLIC_PORT})`);
});
