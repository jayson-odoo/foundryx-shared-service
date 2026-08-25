import { signIn } from 'next-auth/react';
import { apiFetch } from '@/lib/api-client';

export interface SigninCredentials {
  email: string;
  password: string;
  rememberMe?: boolean;
}

/** The backend's current view of the signed-in identity (subset of /auth/me). */
export interface SessionIdentity {
  email: string;
  name: string | null;
  avatar: string | null;
  roles: { id: string; name: string }[];
  permissions: string[];
  isPlatformTenant: boolean;
}

/** Thrown on a failed sign-in. `message` is safe to show the user. */
export class AuthError extends Error {}

export interface AuthService {
  /** Resolves on success; throws {@link AuthError} with a user-safe message on failure. */
  signin(credentials: SigninCredentials): Promise<void>;
  /**
   * Fresh identity from the backend - used to detect a stale session (the
   * change-email ceremony, plan 04, flips the email outside this session's
   * browser context).
   */
  identity(): Promise<SessionIdentity>;
}

// Generic message - must NOT distinguish "no such user" from "wrong password"
// (avoids enumeration; mirrors the backend contract).
const INVALID_CREDENTIALS = 'Invalid email or password.';

/**
 * Auth service - delegates to NextAuth, which POSTs to FastAPI `/auth/login`
 * and stores the returned JWT in the session.
 */
export const authService: AuthService = {
  async signin({ email, password, rememberMe }) {
    const response = await signIn('credentials', {
      redirect: false,
      email,
      password,
      rememberMe,
    });

    if (response?.error) {
      let message = INVALID_CREDENTIALS;
      try {
        const parsed = JSON.parse(response.error) as { message?: string };
        if (parsed.message) message = parsed.message;
      } catch {
        // non-JSON error - keep the generic message
      }
      throw new AuthError(message);
    }
  },

  async identity() {
    const me = await apiFetch<{
      email: string;
      name?: string | null;
      avatar?: string | null;
      roles?: { id: string; name: string }[];
      permissions?: string[];
      isPlatformTenant?: boolean;
    }>('/auth/me');
    return {
      email: me.email,
      name: me.name ?? null,
      avatar: me.avatar ?? null,
      roles: me.roles ?? [],
      permissions: me.permissions ?? [],
      isPlatformTenant: me.isPlatformTenant ?? false,
    };
  },
};
