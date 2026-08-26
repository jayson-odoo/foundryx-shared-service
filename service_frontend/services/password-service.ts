/**
 * Password service (plan 10) - the boundary the forgot/change-password pages
 * talk to (via use-forgot-password / use-change-password). Phase A binds the
 * MOCK; Phase B swaps `passwordService` to the real api-client impl in ONE
 * line (bottom).
 *
 * The interface IS the backend contract (plan 10 §3/§6):
 *   POST /auth/forgot-password  - public, enumeration-safe, ALWAYS 200 with a
 *                                 uniform message; throttled (429 + Retry-After).
 *   POST /auth/set-password     - redeems the single-use token; throttled.
 */
import { InvalidTokenError, RateLimitError } from '@/lib/service-errors';
import { realPasswordService } from './password-service.real';

// Shared identities (lib/service-errors, sprint-2/04 review extraction) -
// re-exported so consumers keep importing from the service boundary.
export { InvalidTokenError, RateLimitError };

export interface PasswordService {
  /**
   * Request a reset link. Resolves with the uniform enumeration-safe message
   * whether or not the account exists. Throws {@link RateLimitError} on 429.
   */
  requestReset(email: string): Promise<{ message: string }>;
  /**
   * Redeem a reset/invite token with a new password. Throws
   * {@link InvalidTokenError} on a bad/expired/used token and
   * {@link RateLimitError} on 429.
   */
  setPassword(token: string, password: string): Promise<void>;
}

// Phase B swap done - mock retained in password-service.mock.ts for tests.
export const passwordService: PasswordService = realPasswordService;
