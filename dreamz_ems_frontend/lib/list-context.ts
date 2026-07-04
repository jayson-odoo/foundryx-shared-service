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
