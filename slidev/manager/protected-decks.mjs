// Protected decks: decks that another part of the platform opens by their folder name.
//
// What it is: Rename moves a deck's folder and Delete removes it, and either would leave that other page on an
// error for everyone. So the manager refuses both for these decks, and the library shows the reason instead of
// those two menu items. Editing, publishing, duplicating, downloading and access work as for any deck.
// Who uses it: deck-actions.mjs (renameDeck and deleteDeck), deck-files.mjs (the library's list) and zone-decks.mjs
// (a protected deck stays with the mission).
// How it fits: plain Node, no packages, so slidev/tests/protected-decks.test.mjs can test it.

// The one list. Empty since round 6: the portal's Dashboards button opens DataEase, no longer the deck
// `mission-dashboard` (which is removed from the live decks at that deploy). Add a folder name (slug) here to
// protect a deck that another page opens by name, then restart the Slidev container.
export const PROTECTED_DECKS = Object.freeze([]);

export const PROTECTED_MESSAGE = 'Another part of the mission portal opens this deck by its name, so it cannot be renamed or deleted. Duplicate it to experiment.';

/** The reason a deck cannot be renamed or deleted, or null when it can. */
export function protectedReason(slug, list = PROTECTED_DECKS) {
  return list.includes(slug) ? PROTECTED_MESSAGE : null;
}

/**
 * Throws (409, with the plain message) when the deck is protected. Called
 * before anything is changed, so a refused rename or delete leaves the deck,
 * its build and its access rule exactly as they were.
 */
export function refuseIfProtected(slug, list = PROTECTED_DECKS) {
  const reason = protectedReason(slug, list);
  if (reason) throw Object.assign(new Error(reason), { status: 409, protectedDeck: true });
}

/** A library entry, marked { protected: true, protected_reason } when protected. */
export function withProtection(deck, list = PROTECTED_DECKS) {
  const reason = protectedReason(deck.slug, list);
  return reason ? { ...deck, protected: true, protected_reason: reason } : deck;
}
