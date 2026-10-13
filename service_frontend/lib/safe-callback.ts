/**
 * The post-sign-in destination from a `?callbackUrl=` query - only a same-origin
 * absolute PATH is honoured (`/portal/ideas`), never an external URL, a
 * protocol-relative `//host`, a backslash trick (`/\host`) or a control
 * character; anything else falls back. Open-redirect guard for `/signin`.
 */
export function safeCallbackPath(raw: string | null | undefined, fallback = '/'): string {
  if (!raw) return fallback;
  if (!raw.startsWith('/') || raw.startsWith('//') || raw.startsWith('/\\')) return fallback;
  if (/[\u0000-\u001f\\]/.test(raw)) return fallback;
  return raw;
}
