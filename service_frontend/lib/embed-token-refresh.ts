/**
 * Silent embed-token re-mint handshake (WS-C3 / AC-CAP-12) — shared by the
 * api-client (data-call 401 retry) AND the session gate (route-mount validate).
 *
 * The embed token is short-lived (5 min) and arrives in the iframe URL fragment.
 * When it expires — on a data call OR when navigating to another embed route —
 * the child asks the HOST (sorento) to re-run its `POST /embed/session` handshake
 * and post a fresh token back. The host validates the child origin before
 * replying; the request carries NO secret (the token flows parent→child).
 */
export const EMBED_TOKEN_REFRESH_REQUEST = 'ideation-embed:token-refresh-request';
export const EMBED_TOKEN_MESSAGE = 'ideation-embed:token';
export const EMBED_REFRESH_TIMEOUT_MS = 8000;

/**
 * Ask the host to silently re-mint the embed token. Resolves with the fresh token
 * from the parent's reply, or null on timeout / no parent. Outbound `postMessage`
 * uses `'*'` (we only RECEIVE the token); the host validates the child origin
 * before replying. Secrets/tokens are never logged.
 */
export function requestEmbedTokenRefresh(): Promise<string | null> {
  if (typeof window === 'undefined' || window.parent === window) {
    return Promise.resolve(null);
  }
  return new Promise((resolve) => {
    let settled = false;
    const finish = (token: string | null) => {
      if (settled) return;
      settled = true;
      window.removeEventListener('message', onMessage);
      clearTimeout(timer);
      resolve(token);
    };
    const onMessage = (event: MessageEvent) => {
      const data = event.data as { type?: unknown; token?: unknown } | null;
      if (data && typeof data === 'object' && data.type === EMBED_TOKEN_MESSAGE) {
        const token = typeof data.token === 'string' ? data.token.trim() : '';
        finish(token || null);
      }
    };
    const timer = setTimeout(() => finish(null), EMBED_REFRESH_TIMEOUT_MS);
    window.addEventListener('message', onMessage);
    window.parent.postMessage({ type: EMBED_TOKEN_REFRESH_REQUEST }, '*');
  });
}
