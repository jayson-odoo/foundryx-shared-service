/**
 * The post-sign-in destination from a `?callbackUrl=` query - only a same-origin
 * absolute PATH is honoured (`/portal/ideas`). The value is resolved the way the
 * browser will resolve it (WHATWG URL against a dummy origin), so a dot-segment
 * trick (`/..//evil`, `/%2e%2e//evil` -> pathname `//evil`) is caught too, along
 * with external URLs, protocol-relative `//host`, backslashes and control
 * characters. Anything else falls back. Open-redirect guard for `/signin`.
 */
const PROBE_ORIGIN = 'http://callback.invalid';

export function safeCallbackPath(raw: string | null | undefined, fallback = '/'): string {
  if (!raw || !raw.startsWith('/') || raw.startsWith('//')) return fallback;
  if (/[\u0000-\u001f\\]/.test(raw)) return fallback;
  let url: URL;
  try {
    url = new URL(raw, PROBE_ORIGIN);
  } catch {
    return fallback;
  }
  if (url.origin !== PROBE_ORIGIN || url.pathname.startsWith('//')) return fallback;
  return `${url.pathname}${url.search}${url.hash}`;
}
