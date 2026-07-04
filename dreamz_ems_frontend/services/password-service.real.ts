/**
 * Real password service — talks to FastAPI via the shared api-client.
 * Wired in Phase B. Endpoints follow plan 10 §6 (public — apiFetch simply
 * has no session token to attach on the auth pages).
 */
import { ApiError, apiFetch } from '@/lib/api-client';
import { deriveTenantSlug } from '@/lib/tenant';
import {
  InvalidTokenError,
  RateLimitError,
  type PasswordService,
} from './password-service';

function mapError(err: unknown): never {
  if (err instanceof ApiError) {
    if (err.status === 429) {
      throw new RateLimitError(err.message, err.retryAfterSeconds);
    }
    // set-password rejects bad/expired/used tokens with 400/404/410.
    if ([400, 404, 410, 422].includes(err.status)) {
      throw new InvalidTokenError(err.message);
    }
  }
  throw err;
}

export const realPasswordService: PasswordService = {
  async requestReset(email: string) {
    try {
      // Tenant resolution mirrors login (plan 07 §6): the host names the tenant.
      const tenantSlug =
        typeof window !== 'undefined'
          ? deriveTenantSlug(window.location.hostname)
          : undefined;
      return await apiFetch<{ message: string }>('/auth/forgot-password', {
        method: 'POST',
        body: JSON.stringify({ email, tenantSlug }),
      });
    } catch (err) {
      mapError(err);
    }
  },

  async setPassword(token: string, password: string) {
    try {
      await apiFetch<unknown>('/auth/set-password', {
        method: 'POST',
        body: JSON.stringify({ token, password }),
      });
    } catch (err) {
      mapError(err);
    }
  },
};
