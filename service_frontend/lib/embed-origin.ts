/**
 * Client mirror of the server's allowed-origin rule (embed access, plan 11H).
 * A valid origin is a bare `scheme://host[:port]` - NO path, trailing slash,
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
  // Exact hostnames only - no wildcards / special chars (a `*.acme.com` entry fed
  // to a CSP frame-ancestors would silently broaden who may embed).
  if (!HOSTNAME_RE.test(url.hostname)) {
    return {
      ok: false,
      error: `"${value}" has an invalid host - wildcards and special characters are not allowed (e.g. https://crm.acme.com).`,
    };
  }
  const isLocal = url.hostname === 'localhost' || url.hostname === '127.0.0.1';
  if (url.protocol === 'http:' && !isLocal) {
    return { ok: false, error: `"${value}" must use https:// (http:// is only allowed for localhost).` };
  }
  // `url.host` already omits the scheme's default port (:443/:80), matching the
  // server's normalization + a browser Origin header.
  return { ok: true, value: `${url.protocol}//${url.host}` };
}

// Dot-separated labels of letters/digits/hyphen (or an IPv4) - mirrors the
// backend `_HOSTNAME_RE`.
const HOSTNAME_RE = /^(?=.{1,253}$)[a-z0-9]([a-z0-9-]{0,62})?(\.[a-z0-9]([a-z0-9-]{0,62})?)*$/i;
