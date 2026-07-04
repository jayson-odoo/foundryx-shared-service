'use client';

import { useCallback, useState } from 'react';
import {
  impersonationStore,
  useImpersonationSession,
  type ImpersonationSession,
} from '@/lib/impersonation-store';
import { impersonationService } from '@/services/impersonation-service';

/**
 * Drives impersonation (plan 03 §13): start (records stay attributed to the real
 * admin server-side), stop, and the active session for the banner + `useCan`.
 */
export function useImpersonation() {
  const session = useImpersonationSession();
  const [pending, setPending] = useState(false);

  const start = useCallback(async (targetUserId: string): Promise<ImpersonationSession> => {
    setPending(true);
    try {
      const s = await impersonationService.start(targetUserId);
      impersonationStore.setSession(s);
      return s;
    } finally {
      setPending(false);
    }
  }, []);

  const stop = useCallback(async (): Promise<void> => {
    setPending(true);
    try {
      await impersonationService.stop();
    } finally {
      impersonationStore.setSession(null);
      setPending(false);
    }
  }, []);

  /** Reconcile the persisted store with the backend's actual active session —
   * clears a stale one (logout-without-exit) or adopts one started elsewhere. */
  const hydrate = useCallback(async (): Promise<void> => {
    try {
      impersonationStore.setSession(await impersonationService.current());
    } catch {
      // Unauthenticated / network blip — leave the store as-is.
    }
  }, []);

  return { session, isImpersonating: Boolean(session), start, stop, hydrate, pending };
}
