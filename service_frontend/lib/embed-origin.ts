/**
 * Client mirror of the server's allowed-origin rule (embed access, plan 11H).
 * A valid origin is a bare `scheme://host[:port]` — NO path, trailing slash,
 * query, fragment, or credentials. `https://` required for real hosts;
 * `http://` allowed ONLY for localhost / 127.0.0.1. The server is the boundary;
 * this is for instant feedback in the origins editor.
 */
export interface OriginCheck {
  ok: boolean;
  /** Normalized origin (lowercased scheme+host, port kept) when `ok`. */
  value?: string;
  error?: string;
}

export function validateEmbedOrigin(raw: string): OriginCheck {
  const value = (raw ?? '').trim();
  if (!value) return { ok: false, error: 'An origin cannot be blank.' };

  let url: URL;
  try {
    url = new URL(value);
  } catch {
    return { ok: false, error: `"${value}" is not a valid origin.` };
  }
  if (url.protocol !== 'https:' && url.protocol !== 'http:') {
    return { ok: false, error: `"${value}" must start with https:// (or http:// for localhost).` };
  }
  if (url.username || url.password) {
    return { ok: false, error: `"${value}" must not include credentials.` };
  }
  if (url.search || url.hash) {
    return { ok: false, error: `"${value}" must not include a query or fragment.` };
  }
  if ((url.pathname && url.pathname !== '/') || value.endsWith('/')) {
    return {
      ok: false,
      error: `"${value}" must be a bare origin with no path or trailing slash (e.g. https://crm.acme.com).`,
    };
  }
  const isLocal = url.hostname === 'localhost' || url.hostname === '127.0.0.1';
  if (url.protocol === 'http:' && !isLocal) {
    return { ok: false, error: `"${value}" must use https:// (http:// is only allowed for localhost).` };
  }
  return { ok: true, value: `${url.protocol}//${url.host}` };
}
