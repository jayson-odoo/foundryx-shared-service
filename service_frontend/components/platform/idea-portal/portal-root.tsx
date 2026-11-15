'use client';

import { useMemo, type ReactNode } from 'react';
import {
  EMBED_PORTAL_PATHS,
  IdeaPortalContext,
  linkPortalPaths,
  PORTAL_PATHS,
  useEmbedPortalSession,
  useLinkPortalSession,
  usePortalSession,
  type IdeaPortalPaths,
  type IdeaPortalRuntime,
  type UsePortalSession,
} from '@/hooks/use-idea-portal';
import { PortalShell } from './portal-shell';
import { PortalSignIn } from './sign-in-view';
import { PortalLoading, PortalMessage } from './portal-states';

function Gate({
  session,
  mode,
  paths,
  children,
}: {
  session: UsePortalSession;
  mode: IdeaPortalRuntime['mode'];
  paths: IdeaPortalPaths;
  children: ReactNode;
}) {
  const runtime = useMemo<IdeaPortalRuntime | null>(
    () =>
      session.principal
        ? {
            mode,
            paths,
            principal: session.principal,
            signOut: session.signOut,
          }
        : null,
    [session.principal, session.signOut, mode, paths],
  );
  if (session.status === 'loading') return <PortalLoading />;
  if (session.status === 'signin' || !runtime) {
    if (mode === 'link') return <PortalMessage text="This link is not valid." />;
    return mode === 'embed' ? <PortalMessage text="Feedback is not available." /> : <PortalSignIn />;
  }
  return (
    <IdeaPortalContext.Provider value={runtime}>
      <PortalShell>{children}</PortalShell>
    </IdeaPortalContext.Provider>
  );
}

/** The shared-service portal (`/portal/feedback/*`). */
export function PortalRoot({ children }: { children: ReactNode }) {
  const session = usePortalSession();
  return (
    <Gate session={session} mode="portal" paths={PORTAL_PATHS}>
      {children}
    </Gate>
  );
}

/** Inside the Sorento iframe (`/embed/feedback/portal/*`), behind the embed session. */
export function EmbedPortalRoot({ embedToken, children }: { embedToken: string | null; children: ReactNode }) {
  const session = useEmbedPortalSession(embedToken);
  return (
    <Gate session={session} mode="embed" paths={EMBED_PORTAL_PATHS}>
      {children}
    </Gate>
  );
}

/** A dealer's personal feedback link (`/public/feedback/{linkToken}/*`, lane
 * PUBLIC-IDEAS-BOARD): the SAME board, no login. */
export function LinkPortalRoot({ linkToken, children }: { linkToken: string; children: ReactNode }) {
  const session = useLinkPortalSession(linkToken);
  const paths = useMemo(() => linkPortalPaths(linkToken), [linkToken]);
  return (
    <Gate session={session} mode="link" paths={paths}>
      {children}
    </Gate>
  );
}
