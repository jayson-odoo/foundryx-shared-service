'use client';

import { Session } from 'next-auth';
import { SessionProvider } from 'next-auth/react';

interface PortalAuthProviderProps {
  children: React.ReactNode;
  session?: Session | null;
}

/**
 * Portal-scoped SessionProvider (AC-06-18). `basePath` points at the SECOND
 * NextAuth handler (`/api/portal-auth`) so `useSession()` inside the
 * `(portal)` tree reads the Profile session — never the staff `(protected)`
 * session, which has its own provider at `/api/auth`.
 */
export function PortalAuthProvider({
  children,
  session,
}: PortalAuthProviderProps) {
  const basePath = process.env.NEXT_PUBLIC_BASE_PATH || '';
  return (
    <SessionProvider
      session={session}
      basePath={`${basePath}/api/portal-auth`}
    >
      {children}
    </SessionProvider>
  );
}
