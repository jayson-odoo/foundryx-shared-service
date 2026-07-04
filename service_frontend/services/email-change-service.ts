/**
 * Email-change service (plan sprint-2/04) — the boundary the account page and
 * the public approve/verify pages talk to. Phase A binds the MOCK; Phase B
 * swaps `emailChangeService` to the real api-client impl in ONE line (bottom).
 *
 * The interface IS the backend contract (plan 04 §Backend):
 *   POST   /me/change-email          — auth'd, self-only; re-enters password;
 *                                      sends approve mail to the OLD address.
 *   GET    /me/change-email          — outstanding request (or none).
 *   DELETE /me/change-email          — cancel the outstanding request.
 *   POST   /auth/approve-email-change — public, single-use OLD-side token;
 *                                      moves PENDING_OLD → PENDING_NEW and
 *                                      sends the verify mail to the NEW address.
 *   POST   /auth/verify-email-change  — public, single-use NEW-side token;
 *                                      flips users.email (uniqueness re-checked).
 */
import { InvalidTokenError, RateLimitError } from '@/lib/service-errors';
import type { PendingEmailChange } from '@/types/account';
import { realEmailChangeService } from './email-change-service.real';

// Shared identities (lib/service-errors, review extraction) — re-exported so
// consumers keep importing from the service boundary.
export { InvalidTokenError, RateLimitError };

/** Password re-entry rejected (wrong current password). */
export class InvalidPasswordError extends Error {}

/** New-side verify lost the uniqueness race — the address is taken (409). */
export class EmailTakenError extends Error {}

export interface EmailChangeService {
  /** The caller's outstanding request, or null when there is none. */
  getPending(): Promise<PendingEmailChange | null>;
  /**
   * Start the ceremony: validates the password (throws
   * {@link InvalidPasswordError}), creates the request (cancelling any prior
   * outstanding one) and mails the approve link to the CURRENT address.
   * Throws {@link RateLimitError} on 429.
   */
  request(newEmail: string, password: string): Promise<PendingEmailChange>;
  /** Cancel the outstanding request (no-op when none). */
  cancel(): Promise<void>;
  /**
   * Redeem the OLD-side approve token. Throws {@link InvalidTokenError} on a
   * bad/expired/used token and {@link RateLimitError} on 429.
   */
  approve(token: string): Promise<void>;
  /**
   * Redeem the NEW-side verify token — this is the step that flips the email.
   * Throws {@link InvalidTokenError} / {@link EmailTakenError} /
   * {@link RateLimitError}.
   */
  verify(token: string): Promise<void>;
}

// Phase B swap done — mock retained in email-change-service.mock.ts for tests.
export const emailChangeService: EmailChangeService = realEmailChangeService;
