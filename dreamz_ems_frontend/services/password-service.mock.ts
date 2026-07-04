/**
 * Mock password service (Phase A). Every page state is tunable with no
 * backend running.
 *
 * Simulation knobs (for dev + tests):
 *   - email containing `throttled`   → requestReset rejects with 429 (15 min)
 *   - any other email                → uniform success (enumeration-safe, like prod)
 *   - token `expired` / `used`/empty → setPassword rejects with InvalidTokenError
 *   - token containing `throttled`   → setPassword rejects with 429 (15 min)
 *   - any other token                → success
 */
import { delay } from './mock-query';
import {
  InvalidTokenError,
  RateLimitError,
  type PasswordService,
} from './password-service';

/** Mirrors the backend's uniform enumeration-safe response (plan 10 D1). */
export const RESET_REQUESTED_MESSAGE =
  'If an account exists for this email, a reset link has been sent.';

const INVALID_TOKEN_MESSAGE =
  'This reset link is invalid or has expired.';

const THROTTLED_MESSAGE = 'Too many attempts.';

export const mockPasswordService: PasswordService = {
  async requestReset(email: string) {
    if (email.includes('throttled')) {
      throw new RateLimitError(THROTTLED_MESSAGE, 15 * 60);
    }
    // Same response whether or not the account exists — the mock keeps the
    // enumeration-safe posture so the UI can never depend on a difference.
    return delay({ message: RESET_REQUESTED_MESSAGE }, 500);
  },

  // eslint-disable-next-line @typescript-eslint/no-unused-vars
  async setPassword(token: string, password: string) {
    if (!token || token.includes('expired') || token.includes('used')) {
      throw new InvalidTokenError(INVALID_TOKEN_MESSAGE);
    }
    if (token.includes('throttled')) {
      throw new RateLimitError(THROTTLED_MESSAGE, 15 * 60);
    }
    return delay(undefined, 500);
  },
};
