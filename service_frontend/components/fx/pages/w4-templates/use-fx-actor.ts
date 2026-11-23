'use client';

import { createContext, useContext } from 'react';
import * as nextAuth from 'next-auth/react';

type SessionValue = { data?: { user?: { name?: string | null } } | null } | undefined;

const NO_SESSION = createContext<SessionValue>(undefined);

/** next-auth's own context, or a stand-in where a test replaces the module
 *  without it. Resolved once. */
const SESSION_CONTEXT: React.Context<SessionValue> = (() => {
  try {
    return (nextAuth.SessionContext as unknown as React.Context<SessionValue>) ?? NO_SESSION;
  } catch {
    return NO_SESSION;
  }
})();

/**
 * Foundryx UIUX switch only: the signed-in person's name for a done toast's
 * "by Kay". Reads the session without requiring a provider (unlike
 * `useSession`), so the legacy look's callers and their tests need nothing new.
 */
export function useFxActor(): string | undefined {
  const session = useContext(SESSION_CONTEXT);
  return session?.data?.user?.name ?? undefined;
}
