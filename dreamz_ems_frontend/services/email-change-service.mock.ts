/**
 * Mock email-change service (Phase A). Every page state is tunable with no
 * backend running.
 *
 * Simulation knobs (for dev + tests):
 *   - password containing `wrong`      → request rejects with InvalidPasswordError
 *   - email containing `throttled`     → request rejects with 429 (15 min)
 *   - any other request                → success, pending row appears (PENDING_OLD)
 *   - token `expired` / `used` / empty → approve/verify reject with InvalidTokenError
 *   - token containing `throttled`     → approve/verify reject with 429 (15 min)
 *   - verify token containing `taken`  → EmailTakenError (uniqueness race, 409)
 *   - any other token                  → success (approve moves the pending row
 *                                        to PENDING_NEW; verify completes it)
 *
 * State is module-local so the account page sees the pending row the dialog
 * just created; tests reset via __resetMockEmailChange().
 */
import type { PendingEmailChange } from '@/types/account';
import {
  EmailTakenError,
  InvalidPasswordError,
  InvalidTokenError,
  RateLimitError,
  type EmailChangeService,
} from './email-change-service';
import { delay } from './mock-query';

const INVALID_PASSWORD_MESSAGE = 'Incorrect password.';
const INVALID_TOKEN_MESSAGE = 'This link is invalid or has expired.';
const EMAIL_TAKEN_MESSAGE = 'This email address is no longer available.';
const THROTTLED_MESSAGE = 'Too many attempts.';

/** One outstanding request max (re-request replaces it — plan 04 data model). */
let pending: PendingEmailChange | null = null;

export function __resetMockEmailChange(initial: PendingEmailChange | null = null) {
  pending = initial;
}

export const mockEmailChangeService: EmailChangeService = {
  async getPending() {
    return delay(pending, 200);
  },

  async request(newEmail: string, password: string) {
    if (newEmail.includes('throttled')) {
      throw new RateLimitError(THROTTLED_MESSAGE, 15 * 60);
    }
    if (password.includes('wrong')) {
      throw new InvalidPasswordError(INVALID_PASSWORD_MESSAGE);
    }
    // Uniqueness is checked server-side with a uniform error (no cross-account
    // enumeration) — the mock mirrors the happy path; Phase B owns the rest.
    pending = {
      newEmail: newEmail.toLowerCase(),
      status: 'PENDING_OLD',
      createdAt: new Date().toISOString(),
      expiresAt: new Date(Date.now() + 60 * 60 * 1000).toISOString(),
    };
    return delay(pending, 400);
  },

  async cancel() {
    pending = null;
    return delay(undefined, 200);
  },

  async approve(token: string) {
    rejectBadToken(token);
    if (pending) pending = { ...pending, status: 'PENDING_NEW' };
    return delay(undefined, 400);
  },

  async verify(token: string) {
    rejectBadToken(token);
    if (token.includes('taken')) {
      throw new EmailTakenError(EMAIL_TAKEN_MESSAGE);
    }
    pending = null;
    return delay(undefined, 400);
  },
};

function rejectBadToken(token: string): void {
  if (!token || token.includes('expired') || token.includes('used')) {
    throw new InvalidTokenError(INVALID_TOKEN_MESSAGE);
  }
  if (token.includes('throttled')) {
    throw new RateLimitError(THROTTLED_MESSAGE, 15 * 60);
  }
}
