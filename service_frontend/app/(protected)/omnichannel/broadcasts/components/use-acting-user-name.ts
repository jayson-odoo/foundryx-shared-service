'use client';

import { useSession } from 'next-auth/react';

/**
 * The signed-in person's name, for "by Kay" in the Foundryx UIUX done
 * toasts. The action registry is also used outside a session provider (unit
 * tests of the list config), where next-auth throws; there the name is
 * simply left out. The hook is always called, so the hook order never
 * changes for a given tree.
 */
export function useActingUserName(): string | undefined {
  try {
    return useSession().data?.user?.name ?? undefined;
  } catch {
    return undefined;
  }
}
