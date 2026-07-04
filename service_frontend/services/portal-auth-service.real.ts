/**
 * Real portal auth service (Cluster E, slice 0a). Login (password + OTP) is
 * delegated to the PORTAL NextAuth handler via `signIn('portal-credentials',
 * { basePath })` so the issued Profile JWT lands in the portal session cookie
 * (independent of the staff session — AC-06-18). The non-login endpoints hit
 * FastAPI directly via portalPublicFetch.
 */
import { signIn } from 'next-auth/react';
import {
  PortalApiError,
  portalPublicFetch,
} from '@/lib/portal-api-client';
import { deriveTenantSlug } from '@/lib/tenant';
import { InvalidTokenError, RateLimitError } from '@/lib/service-errors';
import {
  PortalAuthError,
  type PortalAuthService,
} from './portal-auth-service';

const PORTAL_BASE_PATH = '/api/portal-auth';
const INVALID_CREDENTIALS = 'Invalid email or password.';
const INVALID_CODE = 'Invalid or expired code.';

function tenantSlug(): string | undefined {
  return typeof window !== 'undefined'
    ? deriveTenantSlug(window.location.hostname)
    : undefined;
}

function mapTokenError(err: unknown): never {
  if (err instanceof PortalApiError) {
    if (err.status === 429) {
      throw new RateLimitError(err.message, err.retryAfterSeconds);
    }
    if ([400, 404, 410, 422].includes(err.status)) {
      throw new InvalidTokenError(err.message);
    }
  }
  throw err;
}

/** Pull the user-safe message out of the portal NextAuth error envelope. */
function signinError(error: string | undefined, fallback: string): never {
  let message = fallback;
  try {
    const parsed = JSON.parse(error ?? '') as { message?: string };
    if (parsed.message) message = parsed.message;
  } catch {
    // non-JSON error — keep fallback
  }
  throw new PortalAuthError(message);
}

export const realPortalAuthService: PortalAuthService = {
  async signin({ email, password, rememberMe }) {
    const response = await signIn('portal-credentials', {
      redirect: false,
      email,
      password,
      rememberMe,
      basePath: PORTAL_BASE_PATH,
    });
    if (response?.error) signinError(response.error, INVALID_CREDENTIALS);
  },

  async requestOtp(email: string) {
    try {
      return await portalPublicFetch<{ message: string }>(
        '/portal/auth/request-otp',
        {
          method: 'POST',
          body: JSON.stringify({ email, tenantSlug: tenantSlug() }),
        },
      );
    } catch (err) {
      if (err instanceof PortalApiError && err.status === 429) {
        throw new RateLimitError(err.message, err.retryAfterSeconds);
      }
      throw err;
    }
  },

  async signinOtp({ email, code, rememberMe }) {
    const response = await signIn('portal-credentials', {
      redirect: false,
      email,
      code,
      rememberMe,
      basePath: PORTAL_BASE_PATH,
    });
    if (response?.error) signinError(response.error, INVALID_CODE);
  },

  async requestReset(email: string) {
    try {
      return await portalPublicFetch<{ message: string }>(
        '/portal/auth/forgot-password',
        {
          method: 'POST',
          body: JSON.stringify({ email, tenantSlug: tenantSlug() }),
        },
      );
    } catch (err) {
      if (err instanceof PortalApiError && err.status === 429) {
        throw new RateLimitError(err.message, err.retryAfterSeconds);
      }
      throw err;
    }
  },

  async setPassword(token: string, password: string) {
    try {
      await portalPublicFetch<unknown>('/portal/auth/set-password', {
        method: 'POST',
        body: JSON.stringify({ token, password, tenantSlug: tenantSlug() }),
      });
    } catch (err) {
      mapTokenError(err);
    }
  },
};
