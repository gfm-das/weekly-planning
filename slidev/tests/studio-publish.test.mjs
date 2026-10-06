// GFM Studio: editing only saves; publishing is explicit (Publish now) or queued when the editor is left or stopped.
//   manager/builds.mjs  refreshBuildInBackground does not publish a deck's newer slides while the deck is open in an
//                       editor (a viewer opening the deck would otherwise publish a draft), unless the editor is
//                       being left (publishDraft); ensureDeckBuildWatcher starts no automatic publishing.
// Needs the live layout of the test container (slidev/tests/README.md); skipped without it.
import test, { after } from 'node:test';
import assert from 'node:assert/strict';
import { existsSync } from 'node:fs';
import fs from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';

const LIVE = existsSync('/slidev/node_modules/@slidev/parser') && existsSync('/slidev/manager/builds.mjs');
const skip = LIVE ? false : 'needs the live layout (/slidev/node_modules and /slidev/manager)';

const home = LIVE ? await fs.mkdtemp(path.join(os.tmpdir(), 'studio-publish-')) : '';
if (LIVE) process.env.PRESENTATION_SLIDEV_HOME = home;
const builds = LIVE ? await import('/slidev/manager/builds.mjs') : {};
const settings = LIVE ? await import('/slidev/manager/settings.mjs') : {};

after(async () => { if (home) await fs.rm(home, { recursive: true, force: true }); });

// A deck whose published copy is older than its slides.
async function staleDeck(slug) {
  const dir = path.join(home, 'decks', slug);
  await fs.mkdir(path.join(dir, 'dist'), { recursive: true });
  await fs.writeFile(path.join(dir, 'dist', 'index.html'), '<html></html>');
  const old = new Date(Date.now() - 60000);
  await fs.utimes(path.join(dir, 'dist', 'index.html'), old, old);
  await fs.writeFile(path.join(dir, 'slides.md'), '---\ntitle: T\n---\n\n# T\n');
}

test('editing saves only: no automatic publishing unless SLIDEV_AUTO_PUBLISH=1', { skip }, () => {
  assert.equal(settings.AUTO_PUBLISH_WHILE_EDITING, false);
});

test('slides saved in an open editor are a draft: a viewer opening the deck does not publish them', { skip }, async () => {
  await staleDeck('draft-deck');
  builds.setDraftCheck(slug => slug === 'draft-deck');
  try {
    assert.equal(await builds.refreshBuildInBackground('draft-deck', 60000), false, 'a viewer must not publish a draft');
    assert.equal(await builds.refreshBuildInBackground('draft-deck', 60000, { publishDraft: true }), true, 'leaving the editor queues the publish');
  } finally {
    builds.closeDeckWatcher('draft-deck');
    builds.setDraftCheck(() => false);
  }
});

test('without an editor the newer slides are published as before (opening a deck, an idle editor stopped)', { skip }, async () => {
  await staleDeck('idle-deck');
  builds.setDraftCheck(() => false);
  try {
    assert.equal(await builds.refreshBuildInBackground('idle-deck', 60000), true);
  } finally {
    builds.closeDeckWatcher('idle-deck');
  }
});
