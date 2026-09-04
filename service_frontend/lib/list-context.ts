/**
 * Encode/decode the list query that travels list -> form in the URL, so the
 * form's record-nav can re-run the same server query at index±1 (refresh- and
 * share-safe). Kept tiny + dependency-free. See plan 02 §3b.
 */
import type { ListQuery } from '@/types/resource';

/** URL-safe base64 of the query JSON. */
export function encodeListQuery(query: ListQuery): string {
  try {
    const json = JSON.stringify(query);
    const b64 = typeof window === 'undefined' ? Buffer.from(json).toString('base64') : window.btoa(json);
    return b64.replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '');
  } catch {
    return '';
  }
}

export function decodeListQuery(value: string | null | undefined): ListQuery | null {
  if (!value) return null;
  try {
    const b64 = value.replace(/-/g, '+').replace(/_/g, '/');
    const json = typeof window === 'undefined' ? Buffer.from(b64, 'base64').toString() : window.atob(b64);
    return JSON.parse(json) as ListQuery;
  } catch {
    return null;
  }
}

/**
 * The record-nav wire contract (plan 23 §3.4, AC-DLA-29/30/31): `ctx` (the
 * encoded list query), `i` (the row's global index within it) and `from`
 * (the id of the row the list should restore on Back). Every form URL that
 * carries record-nav carries all three; `use-record-nav.ts` and the
 * `ResourceForm` Back button both build on `buildListNav` so the three never
 * drift out of sync with each other.
 */
export interface ListNavParams {
  ctx?: string | null;
  i?: number | null;
  from?: string | null;
}

export interface ParsedListNav {
  ctx: string | null;
  i: number | null;
  from: string | null;
}

/**
 * Merge `ctx`/`i`/`from` onto an href's own query string (which may already
 * carry unrelated params, e.g. `?edit=1`) - a `null`/`undefined` value DELETES
 * that key rather than leaving a stale one behind. A trailing hash survives
 * (split before the query, reattached after).
 */
export function buildListNav(href: string, params: ListNavParams): string {
  const hashAt = href.indexOf('#');
  const hash = hashAt === -1 ? '' : href.slice(hashAt);
  const base = hashAt === -1 ? href : href.slice(0, hashAt);
  const [path, search = ''] = base.split('?');
  const qs = new URLSearchParams(search);

  if (params.ctx) qs.set('ctx', params.ctx);
  else qs.delete('ctx');

  if (typeof params.i === 'number' && Number.isFinite(params.i)) qs.set('i', String(params.i));
  else if ('i' in params) qs.delete('i');

  if (params.from) qs.set('from', params.from);
  else if ('from' in params) qs.delete('from');

  const qsString = qs.toString();
  return `${path}${qsString ? `?${qsString}` : ''}${hash}`;
}

/** Read `ctx`/`i`/`from` back off a `URLSearchParams`-shaped param bag. */
export function parseListNav(searchParams: { get(key: string): string | null }): ParsedListNav {
  const ctx = searchParams.get('ctx');
  const iRaw = searchParams.get('i');
  const iNum = iRaw === null ? NaN : Number(iRaw);
  const i = Number.isInteger(iNum) && iNum >= 0 ? iNum : null;
  const from = searchParams.get('from');
  return { ctx, i, from };
}
