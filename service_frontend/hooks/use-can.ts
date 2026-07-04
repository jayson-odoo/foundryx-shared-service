'use client';

import { useMemo } from 'react';
import { useSession } from 'next-auth/react';
import { useImpersonationSession } from '@/lib/impersonation-store';

/**
 * Permission gate for the UI (plan 03 §3.4). Reads the effective permission keys
 * from the NextAuth session (a login-time snapshot) — or the impersonation
 * target's keys while impersonating — and answers `can(key)`.
 *
 * UX ONLY — the backend `require_permission` is the real boundary. This just
 * hides/disables controls the user would get a 403 from. Session keys refresh on
 * re-login, so a mid-session RBAC change to the current user isn't reflected in
 * the UI until they sign in again (the backend still enforces it immediately).
 */
export interface UseCanResult {
  can: (key: string) => boolean;
  /** True only once the session has loaded (avoids flicker-gating on load). */
  ready: boolean;
  permissions: Set<string>;
}

export function useCan(): UseCanResult {
  const { data: session, status } = useSession();
  const impersonation = useImpersonationSession();

  return useMemo(() => {
    // While impersonating, gate by the TARGET's keys (so the UI behaves exactly
    // as the impersonated user would experience it); else the real session keys.
    const source = impersonation ? impersonation.permissions : (session?.user?.permissions ?? []);
    const keys = new Set(source);
    return {
      permissions: keys,
      ready: status !== 'loading',
      can: (key: string) => keys.has(key),
    };
  }, [session, status, impersonation]);
}
