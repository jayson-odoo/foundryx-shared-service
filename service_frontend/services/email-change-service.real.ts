/**
 * Real email-change service — talks to FastAPI via the shared api-client.
 * Wired in Phase B (plan 04 §Backend). /me/* endpoints are auth'd self-scope;
 * the approve/verify endpoints are public token redeems (apiFetch simply has
 * no session token to attach on the auth pages).
 */
import { ApiError, apiFetch } from '@/lib/api-client';
import type { PendingEmailChange } from '@/types/account';
import {
  EmailTakenError,
  InvalidPasswordError,
  InvalidTokenError,
  RateLimitError,
  type EmailChangeService,
} from './email-change-service';

function mapRequestError(err: unknown): never {
  if (err instanceof ApiError) {
    if (err.status === 429) {
      throw new RateLimitError(err.message, err.retryAfterSeconds);
    }
    // Password re-entry rejected / validation failure on the new address.
    if ([400, 401, 403, 422].includes(err.status)) {
      throw new InvalidPasswordError(err.message);
    }
  }
  throw err;
}

function mapTokenError(err: unknown): never {
  if (err instanceof ApiError) {
    if (err.status === 429) {
      throw new RateLimitError(err.message, err.retryAfterSeconds);
    }
    // Uniqueness race on the final flip (plan 04 §Backend).
    if (err.status === 409) {
      throw new EmailTakenError(err.message);
    }
    // Bad/expired/used single-use tokens.
    if ([400, 404, 410, 422].includes(err.status)) {
      throw new InvalidTokenError(err.message);
    }
  }
  throw err;
}

export const realEmailChangeService: EmailChangeService = {
  async getPending() {
    return await apiFetch<PendingEmailChange | null>('/me/change-email');
  },

  async request(newEmail: string, password: string) {
    try {
      return await apiFetch<PendingEmailChange>('/me/change-email', {
        method: 'POST',
        body: JSON.stringify({ newEmail, password }),
      });
    } catch (err) {
      mapRequestError(err);
    }
  },

  async cancel() {
    await apiFetch<unknown>('/me/change-email', { method: 'DELETE' });
  },

  async approve(token: string) {
    try {
      await apiFetch<unknown>('/auth/approve-email-change', {
        method: 'POST',
        body: JSON.stringify({ token }),
      });
    } catch (err) {
      mapTokenError(err);
    }
  },

  async verify(token: string) {
    try {
      await apiFetch<unknown>('/auth/verify-email-change', {
        method: 'POST',
        body: JSON.stringify({ token }),
      });
    } catch (err) {
      mapTokenError(err);
    }
  },
};
