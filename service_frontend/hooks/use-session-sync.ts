'use client';

import { useEffect } from 'react';
import { useSession } from 'next-auth/react';
import { authService, type SessionIdentity } from '@/services/auth-service';

/**
 * What the drift check compares — the session fields a backend-side change
 * can invalidate while the session is live (RBAC edits, the change-email
 * ceremony, avatar updates, …).
 */
export interface SessionSnapshot {
  email: string;
  name: string | null;
  avatar: string | null;
  roles: { id: string; name: string }[];
  permissions: string[];
  isPlatformTenant: boolean;
}

/**
 * True when the backend identity diverged from the session — the signal to
 * fire NextAuth `update()` (whose jwt branch re-pulls /auth/me into the
 * token). Order-insensitive on roles/permissions: the backend builds those
 * lists fresh per request, so ordering is not a meaningful difference.
 */
export function sessionDrifted(
  session: SessionSnapshot,
  identity: SessionIdentity,
): boolean {
  if (session.email !== identity.email) return true;
  if ((session.name ?? null) !== identity.name) return true;
  if ((session.avatar ?? null) !== identity.avatar) return true;
  if (session.isPlatformTenant !== identity.isPlatformTenant) return true;
  if (!sameSet(session.permissions, identity.permissions)) return true;
  if (
    !sameSet(
      session.roles.map((r) => r.id),
      identity.roles.map((r) => r.id),
    )
  ) {
    return true;
  }
  return false;
}

function sameSet(a: string[], b: string[]): boolean {
  if (a.length !== b.length) return false;
  const set = new Set(a);
  return b.every((item) => set.has(item));
}

/**
 * Session freshness (plan sprint-2/06 D8) — generalizes plan 04's
 * `useSessionEmailSync` from email-only to the full identity surface:
 * permissions, roles, email, name, avatar, isPlatformTenant. Mounted in the
 * protected layout, so every hard page load reconciles the session with the
 * backend ("permissions reflect once I refresh the page" — no re-login).
 *
 * Deliberately NOT a bare `update()` on mount: update() flips useSession to
 * 'loading', the protected layout swaps the page for its loading state, the
 * page remounts, the effect fires again — an infinite refresh loop (learned
 * in plan 04). Probing /auth/me first makes the sync conditional and
 * therefore self-stabilizing: after one update() the snapshots match and no
 * further update fires.
 *
 * The backend was never stale — `require_permission` resolves fresh from the
 * DB per request. This closes the cosmetic gap (menus, useCan, gated UI).
 */
export function useSessionSync(): void {
  const { data: session, update } = useSession();
  const user = session?.user;

  useEffect(() => {
    if (!user?.email) return;
    let cancelled = false;
    authService
      .identity()
      .then((identity) => {
        if (cancelled) return;
        const snapshot: SessionSnapshot = {
          email: user.email,
          name: user.name ?? null,
          avatar: user.avatar ?? null,
          roles: user.roles ?? [],
          permissions: user.permissions ?? [],
          isPlatformTenant: user.isPlatformTenant ?? false,
        };
        if (sessionDrifted(snapshot, identity)) {
          void update();
        }
      })
      .catch(() => {
        // Best-effort — a failed probe never blocks the page.
      });
    return () => {
      cancelled = true;
    };
    // Keyed on the session email, NOT the session object (whose identity
    // changes per render): probes when the session first becomes available
    // (the protected layout mounts while useSession is still 'loading'), and
    // re-probes only if the email itself flips — which immediately converges
    // (snapshot then matches the backend, no further update fires).
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [user?.email]);
}
