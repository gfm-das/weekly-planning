// The editors (Slidev's Vite dev servers) refuse host names they do not know with 403 "Blocked request. This host is
// not allowed." (IP addresses and localhost always pass). v1.0.20: the chart builder of /studio reads and writes slides
// through the manager address (presentations.<domain>/__slidev/slides/<n>.json), but only the deck address's name was
// allowed, so "Slide 1 could not be read from the editor (error 403)". Now the manager's name is allowed too, and the
// builder's requests reach the editor as requests for its own address (127.0.0.1:<port>). Plain Node.
import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { editorAllowedHosts } from '../manager/settings.mjs';

const read = name => readFileSync(new URL(`../manager/${name}`, import.meta.url), 'utf8');

test('the editors accept the deck address and the manager address by their public names', () => {
  const names = { manager: 'https://presentations.example.org', deck: 'https://decks.example.org' };
  assert.equal(editorAllowedHosts('decks.example.org', names), 'decks.example.org,presentations.example.org');
  assert.equal(editorAllowedHosts('office-box', names), 'office-box,presentations.example.org,decks.example.org');
  assert.equal(editorAllowedHosts('localhost', { manager: '', deck: '' }), '', 'nothing extra without public names');
});

test('the editor is started with those names (not only the deck name)', () => {
  assert.match(read('editors.mjs'), /__VITE_ADDITIONAL_SERVER_ALLOWED_HOSTS: editorAllowedHosts\(\)/);
});

test('the chart builder\'s slide requests go to the editor as requests for its own address', async () => {
  assert.match(read('manager-routes.mjs'), /async function routeBuilderEditorRequest[\s\S]*?proxyToEditor\(req, res, editor, \{ local: true \}\)/);
  // asLocalRequest without loading editors.mjs (it needs http-proxy): its body, run on a request.
  const source = read('editors.mjs');
  const body = source.match(/export function asLocalRequest\(req, port\) \{([\s\S]*?)\n\}/)[1];
  const asLocalRequest = new Function('req', 'port', body);
  const req = { headers: { host: 'presentations.example.org' } };
  asLocalRequest(req, 3101);
  assert.equal(req.headers.host, '127.0.0.1:3101');
  assert.equal(req.headers['x-forwarded-host'], 'presentations.example.org');
});
