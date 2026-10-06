// What the V2 pages ask the manager (manager/v2-routes.mjs). The browser never gets database access: numbers come
// from portal-api through the manager, which decides who may see what.
import { timed } from './perf';
import type { ChartAnswer, Deck } from './types';

export class ApiError extends Error {
  constructor(public status: number, message: string) { super(message); }
}

// The manager's portal bridge (loaded before this script) sends the X-GFM-Request header its data routes need and
// asks the portal to renew an ended sign-in once. Without it (the dev server) the header is added here.
async function call(url: string, init: RequestInit = {}): Promise<any> {
  const bridge = (window as any).PresentationSession;
  try {
    if (bridge?.api) return await bridge.api(url, init);
    const response = await fetch(url, { credentials: 'same-origin', ...init, headers: { 'X-GFM-Request': '1', ...(init.headers || {}) } });
    const data = await response.json().catch(() => ({}));
    if (!response.ok) throw Object.assign(new Error(data.error || `The request failed (${response.status}).`), { status: response.status });
    return data;
  } catch (error) {
    const e = error as Error & { status?: number };
    throw new ApiError(e.status ?? 0, e.message || 'The request failed.');
  }
}

const json = (method: string, body: unknown): RequestInit => ({ method, headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });

export const pageInfo = () => {
  const m = location.pathname.match(/^\/(studio-v2|p-v2|library-v2)(?:\/([a-z0-9-]+))?/);
  return { mode: (m?.[1] ?? '') as 'studio-v2' | 'p-v2' | 'library-v2' | '', slug: m?.[2] ?? '' };
};

export const fetchDeck = (slug: string): Promise<{ deck: Deck; can_edit: boolean; can_manage: boolean }> => timed('deck fetch', () => call(`/api/presentations-v2/${slug}`));
export const saveDeck = (slug: string, deck: Deck) => call(`/api/presentations-v2/${slug}`, json('PUT', { deck }));
export const fetchCatalog = (): Promise<any> => call('/api/charts/catalog');
export const assetUrl = (slug: string, name: string) => `/p-v2-assets/${slug}/${encodeURIComponent(name)}`;

export async function uploadAsset(slug: string, file: File): Promise<string> {
  const ext = (file.name.split('.').pop() || '').toLowerCase().replace('jpeg', 'jpg');
  const stem = file.name.replace(/\.[^.]+$/, '').toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-+|-+$/g, '').slice(0, 40) || 'picture';
  const name = `${stem}-${Date.now().toString(36)}.${ext}`;
  await call(`/api/presentations-v2/${slug}/assets/${name}`, { method: 'PUT', headers: { 'Content-Type': 'application/octet-stream' }, body: file });
  return name;
}

// One request per chart query at a time, kept for a minute (a deck with several charts of the same numbers asks once).
const answers = new Map<string, { at: number; job: Promise<ChartAnswer> }>();
export function queryChart(slug: string, spec: Record<string, any>): Promise<ChartAnswer> {
  const key = `${slug}:${JSON.stringify(spec)}`;
  const hit = answers.get(key);
  if (hit && Date.now() - hit.at < 60_000) return hit.job;
  const job = timed('query', () => call('/api/presentations-v2/query', json('POST', { deck: slug, spec })));
  answers.set(key, { at: Date.now(), job });
  job.catch(() => answers.delete(key));
  return job;
}
export const forgetAnswers = () => answers.clear();

export interface DeckListItem { slug: string; name: string; slides: number; updated_at: string; can_edit: boolean }
export const listDecks = (): Promise<{ can_manage: boolean; decks: DeckListItem[] }> => call('/api/presentations-v2');
export const fetchViewers = (slug: string): Promise<{ access: Record<string, any>; options: Record<string, any> }> => call(`/api/presentations-v2/${slug}/viewers`);
export const saveViewers = (slug: string, rule: Record<string, any>) => call(`/api/presentations-v2/${slug}/viewers`, json('PUT', { rule }));
