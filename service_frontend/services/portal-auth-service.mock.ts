/**
 * Mock portal auth service (Phase A). Every page state is tunable with no
 * backend running.
 *
 * Simulation knobs:
 *   - signin email/pw containing `wrong`   → PortalAuthError (bad credentials)
 *   - signinOtp code !== '123456'          → PortalAuthError (bad code)
 *   - any other login                      → success
 *   - requestOtp/requestReset email `throttled` → 429 (15 min)
 *   - setPassword token expired/used/empty → InvalidTokenError
 *   - setPassword token `throttled`        → 429 (15 min)
 */
import { delay } from './mock-query';
import { InvalidTokenError, RateLimitError } from '@/lib/service-errors';
import {
  PortalAuthError,
  type PortalAuthService,
} from './portal-auth-service';

/** Uniform enumeration-safe responses (mirror the backend always-200 contract). */
export const OTP_REQUESTED_MESSAGE =
  'If an account exists for this email, a verification code has been sent.';
export const RESET_REQUESTED_MESSAGE =
  'If an account exists for this email, a reset link has been sent.';

const INVALID_TOKEN_MESSAGE = 'This link is invalid or has expired.';
const THROTTLED_MESSAGE = 'Too many attempts.';

export const mockPortalAuthService: PortalAuthService = {
  async signin({ email, password }) {
    if (email.includes('wrong') || password.includes('wrong')) {
      throw new PortalAuthError('Invalid email or password.');
    }
    return delay(undefined, 400);
  },

  async requestOtp(email: string) {
    if (email.includes('throttled')) {
      throw new RateLimitError(THROTTLED_MESSAGE, 15 * 60);
    }
    return delay({ message: OTP_REQUESTED_MESSAGE }, 400);
  },

  async signinOtp({ code }) {
    if (code !== '123456') {
      throw new PortalAuthError('Invalid or expired code.');
    }
    return delay(undefined, 400);
  },

  async requestReset(email: string) {
    if (email.includes('throttled')) {
      throw new RateLimitError(THROTTLED_MESSAGE, 15 * 60);
    }
    return delay({ message: RESET_REQUESTED_MESSAGE }, 400);
  },

  // eslint-disable-next-line @typescript-eslint/no-unused-vars
  async setPassword(token: string, password: string) {
    if (!token || token.includes('expired') || token.includes('used')) {
      throw new InvalidTokenError(INVALID_TOKEN_MESSAGE);
    }
    if (token.includes('throttled')) {
      throw new RateLimitError(THROTTLED_MESSAGE, 15 * 60);
    }
    return delay(undefined, 400);
  },
};
