'use client';

import { useSession } from 'next-auth/react';

/**
 * The signed-in user's name for the "by whom" of a Foundryx UIUX done toast
 * (slice W2-WS). The settings hooks that use it are also rendered without a
 * session provider in their own tests, where the name is simply unknown.
 */
export function useFxUserName(): string | undefined {
  try {
    return useSession()?.data?.user?.name ?? undefined;
  } catch {
    return undefined;
  }
}
