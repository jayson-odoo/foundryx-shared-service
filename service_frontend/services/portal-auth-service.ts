/**
 * Portal auth service (Cluster E, slice 0a) — the boundary the portal login /
 * OTP / password pages talk to (via use-portal-* hooks). Phase A binds the MOCK;
 * Phase B swaps `portalAuthService` to the real impl in ONE line (bottom).
 *
 * The interface IS the backend contract:
 *   POST /portal/auth/login {email,password,...}      — password login
 *   POST /portal/auth/request-otp {email,...}         — always 200, emails a code
 *   POST /portal/auth/login-otp {email,code,...}      — OTP login
 *   POST /portal/auth/forgot-password {email,...}     — always 200, enumeration-safe
 *   POST /portal/auth/set-password {token,password,...}— redeem set/reset token
 *
 * Login (password + OTP) goes through the PORTAL NextAuth handler so the issued
 * Profile JWT lands in the portal session cookie. The non-login endpoints go
 * direct via portalPublicFetch (no session needed).
 */
import { InvalidTokenError, RateLimitError } from '@/lib/service-errors';
import { realPortalAuthService } from './portal-auth-service.real';

export { InvalidTokenError, RateLimitError };

/** Thrown on a failed portal sign-in. `message` is safe to show the user. */
export class PortalAuthError extends Error {}

export interface PortalPasswordCredentials {
  email: string;
  password: string;
  rememberMe?: boolean;
}

export interface PortalOtpCredentials {
  email: string;
  code: string;
  rememberMe?: boolean;
}

export interface PortalAuthService {
  /** Password login → portal NextAuth session. Throws {@link PortalAuthError}. */
  signin(credentials: PortalPasswordCredentials): Promise<void>;
  /** Request an email verification code. Uniform 200 either way; throws {@link RateLimitError} on 429. */
  requestOtp(email: string): Promise<{ message: string }>;
  /** OTP login → portal NextAuth session. Throws {@link PortalAuthError}. */
  signinOtp(credentials: PortalOtpCredentials): Promise<void>;
  /** Self-service forgot-password. Uniform 200; throws {@link RateLimitError} on 429. */
  requestReset(email: string): Promise<{ message: string }>;
  /** Redeem a set/reset token. Throws {@link InvalidTokenError} / {@link RateLimitError}. */
  setPassword(token: string, password: string): Promise<void>;
}

// Phase B swap — mock retained in portal-auth-service.mock.ts for tests.
export const portalAuthService: PortalAuthService = realPortalAuthService;
