import { getSession } from 'next-auth/react';
import { embedAuthStore } from '@/lib/embed-auth-store';
import { requestEmbedTokenRefresh } from '@/lib/embed-token-refresh';
import { impersonationStore } from '@/lib/impersonation-store';
import { deriveTenantSlug } from '@/lib/tenant';

/**
 * Shared API client for the FastAPI backend.
 * Per ADR layering: UI -> hooks -> services -> lib/api-client -> FastAPI.
 * Attaches the NextAuth session JWT (issued by FastAPI) as a Bearer token.
 */

const BASE_URL =
  process.env.NEXT_PUBLIC_BACKEND_API_URL ?? 'http://localhost:8000';

export class ApiError extends Error {
  status: number;
  /** Seconds from the `Retry-After` header on a 429 throttle response. */
  retryAfterSeconds: number | null;
  /** Structured `detail` body when the backend sends an object (e.g. the
   * form engine's 422 `{problems}` / `{fieldErrors}` contracts) — `message`
   * always stays a string. */
  detail: unknown;
  constructor(
    message: string,
    status: number,
    retryAfterSeconds: number | null = null,
    detail: unknown = undefined,
  ) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
    this.retryAfterSeconds = retryAfterSeconds;
    this.detail = detail;
  }
}

/** Parse the (delta-seconds form of the) Retry-After header, if present. */
function retryAfterSecondsOf(res: Response): number | null {
  const raw = res.headers.get('Retry-After');
  if (!raw) return null;
  const seconds = Number(raw);
  return Number.isFinite(seconds) ? seconds : null;
}

/**
 * The backend JWT exp is the real session boundary (plan 10 D4): a 401 on a
 * request that DID carry a token means the token expired or was revoked —
 * end the NextAuth session and return to signin. (Permission problems are
 * 403s; they never land here.)
 */
async function endSessionOn401(hadToken: boolean, status: number): Promise<void> {
  if (status !== 401 || !hadToken || typeof window === 'undefined') return;
  const { signOut } = await import('next-auth/react');
  await signOut({ callbackUrl: '/signin' });
}

// ── Ideation embed silent re-mint (WS-C3 / AC-CAP-12) ────────────────────────
// The embed token is short-lived (5 min); an interactive grid outlives it. On a
// 401 for an `/embed/*` data call in the embed runtime, ask the HOST (parent
// frame) to re-mint via its `/embed/session` handshake, then retry ONCE. Gated
// to retry a single time so a persistently-failing token can't infinite-loop.
//
// TODO(cross-repo, sorento host — IdeationEmbed.tsx): the host iframe wrapper
// MUST listen for `{type:'ideation-embed:token-refresh-request'}` from this
// child, re-run its `POST /embed/session` handshake, and post
// `{type:'ideation-embed:token', token}` back to the iframe. That companion
// change ships separately (NOT in this repo). Until it lands, a refresh times
// out and the embed degrades to the clean "session expired" state.
/** True for embed data calls that may re-mint on 401 — never the token gate
 * (`/embed/validate`) or the SSO exchange (`/embed/session`) themselves. */
function isRemintableEmbedPath(path: string): boolean {
  return (
    path.startsWith('/embed/') &&
    !path.startsWith('/embed/validate') &&
    !path.startsWith('/embed/session')
  );
}

/**
 * Attach the request's auth + tenant headers and report how the request should
 * handle a 401. In the omnichannel EMBED runtime (an in-memory
 * `embedAuthStore` session) the credential is the `/embed/session` access
 * token, NOT the NextAuth JWT — so we skip `getSession()` and, critically,
 * never `signOut()` on a 401 (the iframe has no NextAuth session to end; a
 * near-expiry token is refreshed via the postMessage `needToken` handshake).
 * Everywhere else this is the unchanged NextAuth Bearer path.
 */
async function attachAuth(headers: Headers): Promise<{ hadToken: boolean; signOutOn401: boolean }> {
  const embed = embedAuthStore.getState();
  if (embed) {
    headers.set('Authorization', `Bearer ${embed.accessToken}`);
    if (typeof window !== 'undefined') {
      headers.set('X-Tenant-Slug', deriveTenantSlug(window.location.hostname));
    }
    return { hadToken: true, signOutOn401: false };
  }

  const session = await getSession();
  const token = session?.accessToken;
  if (token) headers.set('Authorization', `Bearer ${token}`);
  // Defense-in-depth: name the tenant the browser believes it's on (plan 07
  // §6). The JWT claim stays the source of truth server-side.
  if (typeof window !== 'undefined') {
    headers.set('X-Tenant-Slug', deriveTenantSlug(window.location.hostname));
  }
  // While impersonating, signal the effective (target) user. The backend honors
  // it only with an active session; the real admin stays the actor.
  const impersonation = impersonationStore.getState();
  if (impersonation) headers.set('X-Impersonate-User-Id', impersonation.targetUser.id);
  return { hadToken: Boolean(token), signOutOn401: Boolean(token) };
}

export async function apiFetch<T = unknown>(
  path: string,
  init: RequestInit = {},
): Promise<T> {
  return apiFetchOnce<T>(path, init, true);
}

async function apiFetchOnce<T>(
  path: string,
  init: RequestInit,
  allowEmbedRefresh: boolean,
): Promise<T> {
  const headers = new Headers(init.headers);
  if (!headers.has('Content-Type') && !(init.body instanceof FormData)) {
    headers.set('Content-Type', 'application/json');
  }
  const { signOutOn401 } = await attachAuth(headers);

  const res = await fetch(`${BASE_URL}${path}`, { ...init, headers });

  if (!res.ok) {
    // WS-C3: silent embed re-mint on expiry — a 401 on an /embed/* data call in
    // the embed runtime asks the host for a fresh token and retries ONCE.
    if (
      res.status === 401 &&
      allowEmbedRefresh &&
      embedAuthStore.getState() !== null &&
      isRemintableEmbedPath(path)
    ) {
      const fresh = await requestEmbedTokenRefresh();
      if (fresh) {
        embedAuthStore.setToken(fresh);
        return apiFetchOnce<T>(path, init, false); // retry once, no further re-mint
      }
    }
    let message = res.statusText || 'Request failed';
    let detail: unknown;
    try {
      const data = await res.json();
      detail = data.detail;
      // message stays a STRING — object details ride ApiError.detail.
      message =
        (typeof data.detail === 'string' ? data.detail : undefined) ?? data.message ?? message;
    } catch {
      // non-JSON error body (proxy HTML, network blip)
    }
    await endSessionOn401(signOutOn401, res.status);
    throw new ApiError(message, res.status, retryAfterSecondsOf(res), detail);
  }

  if (res.status === 204) return undefined as T;
  return (await res.json()) as T;
}

/** Like {@link apiFetch} but returns the raw response body as text (e.g. CSV export). */
export async function apiFetchText(path: string, init: RequestInit = {}): Promise<string> {
  const headers = new Headers(init.headers);
  if (!headers.has('Content-Type') && !(init.body instanceof FormData)) {
    headers.set('Content-Type', 'application/json');
  }
  const { signOutOn401 } = await attachAuth(headers);

  const res = await fetch(`${BASE_URL}${path}`, { ...init, headers });
  if (!res.ok) {
    await endSessionOn401(signOutOn401, res.status);
    throw new ApiError(res.statusText || 'Request failed', res.status);
  }
  return res.text();
}

/**
 * Like {@link apiFetch} but returns the raw response body as a Blob — for authed
 * binary endpoints: a file/PDF the browser must fetch with the Bearer (an
 * `<img>`/`<a href>` can't carry the JWT), e.g. a submission's uploaded file or
 * `POST /templates/preview?format=pdf`. The Content-Type/tenant/impersonation
 * headers attach as elsewhere; the caller object-URLs the blob.
 */
export async function apiFetchBlob(path: string, init: RequestInit = {}): Promise<Blob> {
  const headers = new Headers(init.headers);
  if (!headers.has('Content-Type') && !(init.body instanceof FormData)) {
    headers.set('Content-Type', 'application/json');
  }
  const { signOutOn401 } = await attachAuth(headers);

  const res = await fetch(`${BASE_URL}${path}`, { ...init, headers });
  if (!res.ok) {
    let message = res.statusText || 'Request failed';
    let detail: unknown;
    try {
      const data = await res.json();
      detail = data.detail;
      message =
        (typeof data.detail === 'string' ? data.detail : undefined) ?? data.message ?? message;
    } catch {
      // non-JSON error body
    }
    await endSessionOn401(signOutOn401, res.status);
    throw new ApiError(message, res.status, retryAfterSecondsOf(res), detail);
  }
  return res.blob();
}

/**
 * Unauthenticated fetch for pre-auth public surfaces (slice-2 public form fill;
 * mirrors the branding public routes). NO session lookup, NO Bearer, NO
 * sign-out-on-401 (there is no session to end) — but preserves `ApiError.detail`
 * so a public submit's 422 `{fieldErrors}` still reaches the renderer. `FormData`
 * bodies skip the JSON content-type (multipart upload path).
 */
export async function publicFetch<T = unknown>(
  path: string,
  init: RequestInit = {},
): Promise<T> {
  const headers = new Headers(init.headers);
  if (!headers.has('Content-Type') && !(init.body instanceof FormData)) {
    headers.set('Content-Type', 'application/json');
  }
  const res = await fetch(`${BASE_URL}${path}`, { ...init, headers });
  if (!res.ok) {
    let message = res.statusText || 'Request failed';
    let detail: unknown;
    try {
      const data = await res.json();
      detail = data.detail;
      message =
        (typeof data.detail === 'string' ? data.detail : undefined) ?? data.message ?? message;
    } catch {
      // non-JSON error body
    }
    throw new ApiError(message, res.status, retryAfterSecondsOf(res), detail);
  }
  if (res.status === 204) return undefined as T;
  return (await res.json()) as T;
}
