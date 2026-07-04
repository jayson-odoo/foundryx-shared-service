'use client';

import { useCallback, useEffect, useSyncExternalStore } from 'react';
import { useSession } from 'next-auth/react';
import type { TerminologyMap } from '@/types/terminology';
import { portalTerminologyService } from '@/services/portal-terminology-service';
import { humanize, type UseTerminologyResult } from './use-terminology';

/**
 * Portal terminology hook (Cluster E portal-signout fix, sprint-4/06).
 *
 * Same shape/interface as the staff `useTerminology()` (`label`/`labelPlural`/
 * `t(key,count)` + humanized fallback, fetch-once store) but resolved through
 * the PORTAL api-client + the Profile-authed `GET /portal/terminology`. The
 * `(portal)` tree must NEVER call the staff `useTerminology` / `apiFetch` — that
 * hits the staff-only `GET /terminology`, which 401s the Profile JWT and signs
 * the Profile out (the bug this fixes). Its own module store keeps the staff and
 * portal label caches isolated.
 */

type MapState = { map: TerminologyMap | null };

let state: MapState = { map: null };
let promise: Promise<void> | null = null;
const listeners = new Set<() => void>();

function emit(): void {
  listeners.forEach((l) => l());
}

function fetchTerminology(token: string | null): Promise<void> {
  promise ??= portalTerminologyService
    .getTerminology(token)
    .then((map) => {
      state = { map };
    })
    .catch(() => {
      // Degrade to humanized fallbacks — never block render or signout.
      state = { map: state.map ?? {} };
    })
    .finally(() => {
      promise = null;
      emit();
    });
  return promise;
}

function subscribe(listener: () => void): () => void {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

const getSnapshot = (): MapState => state;
const getServerSnapshot = (): MapState => ({ map: null });

export function usePortalTerminology(): UseTerminologyResult {
  const { data: session, status } = useSession();
  const token =
    (session as unknown as { accessToken?: string } | null)?.accessToken ?? null;

  // Fetch once the Profile session has resolved with a token (gating on a token
  // avoids sending a null-auth request that 401s and stays empty forever).
  useEffect(() => {
    if (status === 'loading') return;
    if (state.map !== null || promise !== null) return;
    if (!token) return;
    void fetchTerminology(token);
  }, [status, token]);

  const s = useSyncExternalStore(subscribe, getSnapshot, getServerSnapshot);
  const map = s.map;

  const label = useCallback(
    (key: string) => map?.[key]?.singular ?? humanize(key),
    [map],
  );
  const labelPlural = useCallback(
    (key: string) => map?.[key]?.plural ?? `${humanize(key)}s`,
    [map],
  );
  const t = useCallback(
    (key: string, count: number) => (count === 1 ? label(key) : labelPlural(key)),
    [label, labelPlural],
  );

  const refetch = useCallback(async () => {
    state = { map: state.map };
    promise = null;
    if (token) await fetchTerminology(token);
  }, [token]);

  return { ready: map !== null, label, labelPlural, t, refetch };
}
