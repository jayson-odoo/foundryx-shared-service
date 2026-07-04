'use client';

import { useCallback, useEffect, useState } from 'react';
import { useSession } from 'next-auth/react';
import {
  portalSurfaceService,
  type PortalSurface,
} from '@/services/portal-surface-service';

/**
 * Loads the Profile's accessible portal surfaces (AC-06-24). Reads the PORTAL
 * session token (the portal SessionProvider's basePath) and passes it to the
 * service so the api-client skips the extra session round-trip.
 *
 * Layering: portal UI → THIS hook → service → portal-api-client → FastAPI. A
 * component never fetches directly.
 */
export interface UsePortalSurfacesResult {
  surfaces: PortalSurface[];
  loading: boolean;
  error: string | null;
  reload: () => void;
}

export function usePortalSurfaces(): UsePortalSurfacesResult {
  const { data: session, status } = useSession();
  const token = (session as unknown as { accessToken?: string } | null)
    ?.accessToken;

  const [surfaces, setSurfaces] = useState<PortalSurface[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [nonce, setNonce] = useState(0);

  const reload = useCallback(() => setNonce((n) => n + 1), []);

  useEffect(() => {
    // Wait for the session to resolve so we attach the Profile token.
    if (status === 'loading') return;
    let active = true;
    setLoading(true);
    setError(null);
    portalSurfaceService
      .listSurfaces(token ?? null)
      .then((data) => {
        if (active) setSurfaces(data);
      })
      .catch((e: unknown) => {
        if (active) {
          setError(e instanceof Error ? e.message : 'Could not load the portal.');
          setSurfaces([]);
        }
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => {
      active = false;
    };
  }, [status, token, nonce]);

  return { surfaces, loading, error, reload };
}
