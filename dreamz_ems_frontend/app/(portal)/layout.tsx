import { ReactNode, Suspense } from 'react';
import { PortalAuthProvider } from '@/providers/portal-auth-provider';
import { PortalFilterProvider } from '@/providers/portal-filter-provider';

/**
 * Profile Portal route group (Cluster E).
 *
 * - slice 0a: the portal lives behind its OWN NextAuth SessionProvider, pointed
 *   at the second handler (`/api/portal-auth`) via `basePath`. The staff
 *   `(protected)` tree keeps its own provider at `/api/auth`; the two NEVER
 *   share a provider or a session cookie.
 * - slice 0b: the `PortalFilterProvider` carries the global event/context filter
 *   (`?ctx=`) so it applies app-wide across every portal surface (AC-06-25). It
 *   reads `useSearchParams`, so it sits inside a Suspense boundary.
 */
export default function PortalLayout({ children }: { children: ReactNode }) {
  return (
    <PortalAuthProvider>
      <Suspense fallback={null}>
        <PortalFilterProvider>{children}</PortalFilterProvider>
      </Suspense>
    </PortalAuthProvider>
  );
}
