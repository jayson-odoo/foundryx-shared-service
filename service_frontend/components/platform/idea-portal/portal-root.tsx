'use client';

import { useMemo, type ReactNode } from 'react';
import {
  EMBED_PORTAL_PATHS,
  IdeaPortalContext,
  PORTAL_PATHS,
  useEmbedPortalSession,
  usePortalSession,
  type IdeaPortalRuntime,
  type UsePortalSession,
} from '@/hooks/use-idea-portal';
import { PortalShell } from './portal-shell';
import { PortalSignIn } from './sign-in-view';
import { PortalLoading, PortalMessage } from './portal-states';

function Gate({
  session,
  mode,
  children,
}: {
  session: UsePortalSession;
  mode: 'portal' | 'embed';
  children: ReactNode;
}) {
  const runtime = useMemo<IdeaPortalRuntime | null>(
    () =>
      session.principal
        ? {
            mode,
            paths: mode === 'embed' ? EMBED_PORTAL_PATHS : PORTAL_PATHS,
            principal: session.principal,
            signOut: session.signOut,
          }
        : null,
    [session.principal, session.signOut, mode],
  );
  if (session.status === 'loading') return <PortalLoading />;
  if (session.status === 'signin' || !runtime) {
    return mode === 'embed' ? <PortalMessage text="Ideas are not available." /> : <PortalSignIn />;
  }
  return (
    <IdeaPortalContext.Provider value={runtime}>
      <PortalShell>{children}</PortalShell>
    </IdeaPortalContext.Provider>
  );
}

/** The shared-service portal (`/portal/ideas/*`). */
export function PortalRoot({ children }: { children: ReactNode }) {
  const session = usePortalSession();
  return (
    <Gate session={session} mode="portal">
      {children}
    </Gate>
  );
}

/** Inside the Sorento iframe (`/embed/ideas/portal/*`), behind the embed session. */
export function EmbedPortalRoot({ embedToken, children }: { embedToken: string | null; children: ReactNode }) {
  const session = useEmbedPortalSession(embedToken);
  return (
    <Gate session={session} mode="embed">
      {children}
    </Gate>
  );
}
