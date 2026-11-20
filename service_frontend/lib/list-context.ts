/**
 * Encode/decode the list query that travels list -> form in the URL, so the
 * form's record-nav can re-run the same server query at index±1 (refresh- and
 * share-safe). Kept tiny + dependency-free. See plan 02 §3b.
 */
import type { FilterGroup, FilterRule, ListQuery, SortState, StatusView } from '@/types/resource';

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

const STATUS_VIEWS: StatusView[] = ['active', 'trashed'];

function isPlainObject(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function isValidSort(value: unknown): value is SortState | null | undefined {
  if (value === null || value === undefined) return true;
  return isPlainObject(value) && typeof value.id === 'string' && typeof value.desc === 'boolean';
}

/**
 * Shallow-but-real shape check on a filter rule/group - deep enough to catch
 * a foreign payload (wrong `kind`, a non-array `rules`, a non-string
 * `field`), not a full re-validation of every operator/value combination
 * (that is the SERVER's job via `filter_translator.py`'s own whitelist -
 * this is only about refusing to hand a malformed tree to the filter
 * builder UI, not re-litigating what's a legal filter).
 */
function isValidFilterRule(value: unknown, depth = 0): value is FilterRule {
  if (depth > 8 || !isPlainObject(value)) return false;
  if (value.kind === 'condition') {
    return typeof value.field === 'string' && typeof value.operator === 'string';
  }
  if (value.kind === 'group') {
    return (
      (value.combinator === 'and' || value.combinator === 'or') &&
      Array.isArray(value.rules) &&
      value.rules.every((rule) => isValidFilterRule(rule, depth + 1))
    );
  }
  return false;
}

function isValidFilter(value: unknown): value is FilterGroup | null | undefined {
  if (value === null || value === undefined) return true;
  return isValidFilterRule(value);
}

/**
 * Shape-guards a decoded `ctx` payload against the `ListQuery` contract (fix
 * round 2) - `JSON.parse` on a tampered/foreign `ctx` (or one crafted by
 * hand) happily returns ANY object shape; without this check a
 * structurally-wrong payload sailed straight into `useResourceList`'s state
 * (page/pageSize as non-numbers, an unknown `statusView`, ...) with no
 * further validation downstream. Every field beyond `page`/`pageSize` is
 * OPTIONAL per `ListQuery`, so `undefined` passes; a WRONG type never does.
 */
function isValidListQuery(value: unknown): value is ListQuery {
  if (!isPlainObject(value)) return false;
  if (!Number.isInteger(value.page) || (value.page as number) < 0) return false;
  if (!Number.isInteger(value.pageSize) || (value.pageSize as number) < 0) return false;
  if (value.search !== undefined && typeof value.search !== 'string') return false;
  if (!isValidSort(value.sort)) return false;
  if (!isValidFilter(value.filter)) return false;
  if (value.statusView !== undefined && !STATUS_VIEWS.includes(value.statusView as StatusView)) return false;
  if (value.segment !== undefined && typeof value.segment !== 'string') return false;
  return true;
}

export function decodeListQuery(value: string | null | undefined): ListQuery | null {
  if (!value) return null;
  try {
    const b64 = value.replace(/-/g, '+').replace(/_/g, '/');
    const json = typeof window === 'undefined' ? Buffer.from(b64, 'base64').toString() : window.atob(b64);
    const parsed: unknown = JSON.parse(json);
    return isValidListQuery(parsed) ? parsed : null;
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

  // Every key follows the same "omitted key = leave the href's own value
  // alone, explicit null/undefined = delete" rule (a real bug this fixed:
  // `use-record-nav.ts` calls this with ONLY `{ from }` - `buildHref` already
  // embedded `ctx` in the href it built, and an unconditional delete-when-
  // falsy on `ctx` here was silently dropping it from every record-nav step).
  if (params.ctx) qs.set('ctx', params.ctx);
  else if ('ctx' in params) qs.delete('ctx');

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
