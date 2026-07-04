import { deriveTenantSlug } from '@/lib/tenant';

/**
 * Portal-scoped API client (Cluster E, AC-06-18). Mirrors lib/api-client.ts but
 * for the PROFILE session — it must NOT touch the staff session.
 *
 * Token read: NextAuth's `getSession()` uses a process-global basePath (the
 * staff `/api/auth`), so it is NOT reusable for the second session. Instead we
 * either accept the token from the calling hook (`useSession()` inside the
 * portal provider) or read `/api/portal-auth/session` directly. On a
 * 401-with-token we sign out of the PORTAL session ONLY.
 *
 * Layering: portal UI → hook → service → portal-api-client → FastAPI.
 */
const BASE_URL =
  process.env.NEXT_PUBLIC_BACKEND_API_URL ?? 'http://localhost:8000';

const PORTAL_SESSION_ENDPOINT = '/api/portal-auth/session';

export class PortalApiError extends Error {
  status: number;
  retryAfterSeconds: number | null;
  detail: unknown;
  constructor(
    message: string,
    status: number,
    retryAfterSeconds: number | null = null,
    detail: unknown = undefined,
  ) {
    super(message);
    this.name = 'PortalApiError';
    this.status = status;
    this.retryAfterSeconds = retryAfterSeconds;
    this.detail = detail;
  }
}

export interface PortalFetchOptions extends RequestInit {
  /**
   * Bearer token from the portal session. When omitted, the client reads it
   * from the portal session endpoint — pass it from `useSession()` to skip the
   * extra round-trip.
   */
  token?: string | null;
}

function retryAfterSecondsOf(res: Response): number | null {
  const raw = res.headers.get('Retry-After');
  if (!raw) return null;
  const seconds = Number(raw);
  return Number.isFinite(seconds) ? seconds : null;
}

/** Read the Profile access token from the PORTAL session endpoint (never the staff one). */
async function readPortalToken(): Promise<string | null> {
  if (typeof window === 'undefined') return null;
  try {
    const basePath = process.env.NEXT_PUBLIC_BASE_PATH || '';
    const res = await fetch(`${basePath}${PORTAL_SESSION_ENDPOINT}`, {
      headers: { 'Content-Type': 'application/json' },
    });
    if (!res.ok) return null;
    const session = (await res.json()) as { accessToken?: string } | null;
    return session?.accessToken ?? null;
  } catch {
    return null;
  }
}

/** End the PORTAL session on a 401-with-token (the Profile JWT expired/was revoked). */
async function endPortalSessionOn401(
  hadToken: boolean,
  status: number,
): Promise<void> {
  if (status !== 401 || !hadToken || typeof window === 'undefined') return;
  const { signOut } = await import('next-auth/react');
  await signOut({
    callbackUrl: '/portal/login',
    // Target the portal handler so the right (portal) cookie is cleared.
  });
}

export async function portalApiFetch<T = unknown>(
  path: string,
  init: PortalFetchOptions = {},
): Promise<T> {
  const { token: providedToken, ...requestInit } = init;
  const token =
    providedToken !== undefined ? providedToken : await readPortalToken();

  const headers = new Headers(requestInit.headers);
  if (
    !headers.has('Content-Type') &&
    !(requestInit.body instanceof FormData)
  ) {
    headers.set('Content-Type', 'application/json');
  }
  if (token) headers.set('Authorization', `Bearer ${token}`);
  if (typeof window !== 'undefined') {
    headers.set('X-Tenant-Slug', deriveTenantSlug(window.location.hostname));
  }

  const res = await fetch(`${BASE_URL}${path}`, { ...requestInit, headers });

  if (!res.ok) {
    let message = res.statusText || 'Request failed';
    let detail: unknown;
    try {
      const data = await res.json();
      detail = data.detail;
      message =
        (typeof data.detail === 'string' ? data.detail : undefined) ??
        data.message ??
        message;
    } catch {
      // non-JSON error body
    }
    await endPortalSessionOn401(Boolean(token), res.status);
    throw new PortalApiError(
      message,
      res.status,
      retryAfterSecondsOf(res),
      detail,
    );
  }

  if (res.status === 204) return undefined as T;
  return (await res.json()) as T;
}

/**
 * Profile-session blob fetch (Cluster E portal fix) — the portal twin of the
 * staff `apiFetchBlob`. Used for the authed CSP-sandboxed file/signature serve
 * routes (an <a href> can't carry the Bearer). Profile-session bound; on a
 * 401-with-token it ends the PORTAL session only — NEVER the staff one.
 */
export async function portalApiFetchBlob(
  path: string,
  init: PortalFetchOptions = {},
): Promise<Blob> {
  const { token: providedToken, ...requestInit } = init;
  const token =
    providedToken !== undefined ? providedToken : await readPortalToken();

  const headers = new Headers(requestInit.headers);
  if (!headers.has('Content-Type') && !(requestInit.body instanceof FormData)) {
    headers.set('Content-Type', 'application/json');
  }
  if (token) headers.set('Authorization', `Bearer ${token}`);
  if (typeof window !== 'undefined') {
    headers.set('X-Tenant-Slug', deriveTenantSlug(window.location.hostname));
  }

  const res = await fetch(`${BASE_URL}${path}`, { ...requestInit, headers });
  if (!res.ok) {
    let message = res.statusText || 'Request failed';
    let detail: unknown;
    try {
      const data = await res.json();
      detail = data.detail;
      message =
        (typeof data.detail === 'string' ? data.detail : undefined) ??
        data.message ??
        message;
    } catch {
      // non-JSON error body
    }
    await endPortalSessionOn401(Boolean(token), res.status);
    throw new PortalApiError(
      message,
      res.status,
      retryAfterSecondsOf(res),
      detail,
    );
  }
  return res.blob();
}

/**
 * Unauthenticated portal fetch for the pre-auth portal surfaces (login, OTP
 * request, forgot/set-password). NO session lookup, NO Bearer, NO sign-out —
 * but preserves PortalApiError.detail / Retry-After so throttle (429) and
 * field errors reach the hooks.
 */
export async function portalPublicFetch<T = unknown>(
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
        (typeof data.detail === 'string' ? data.detail : undefined) ??
        data.message ??
        message;
    } catch {
      // non-JSON error body
    }
    throw new PortalApiError(
      message,
      res.status,
      retryAfterSecondsOf(res),
      detail,
    );
  }
  if (res.status === 204) return undefined as T;
  return (await res.json()) as T;
}
