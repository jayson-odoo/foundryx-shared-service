'use client';

import { useCallback, useEffect, useState } from 'react';
import { ApiError } from '@/lib/api-client';
import { hubConnectorService } from '@/services/hub-connector-service';
import type {
  ApiKeyCreated,
  Hub,
  HubCreateInput,
  HubCreated,
  Option,
  OptionKind,
  SyncState,
} from '@/types/hub-connector';

/**
 * Hub Connector hooks - the screens' only way to the service layer
 * (UI -> hook -> service -> api-client). Lists read through their ResourceList
 * fetchers; these cover the mutations and the non-list reads.
 */

/** Plain message for a failed call: the backend's `{code, message}` detail, else the error text. */
export function hubConnectorErrorMessage(err: unknown, fallback: string): string {
  if (err instanceof ApiError) {
    const detail = err.detail as { message?: unknown } | undefined;
    if (detail && typeof detail.message === 'string' && detail.message) return detail.message;
    if (err.message) return err.message;
  }
  return fallback;
}

/** Run one async call with a busy flag. */
function useBusy<A extends unknown[], R>(fn: (...args: A) => Promise<R>) {
  const [busy, setBusy] = useState(false);
  const run = useCallback(
    async (...args: A): Promise<R> => {
      setBusy(true);
      try {
        return await fn(...args);
      } finally {
        setBusy(false);
      }
    },
    [fn],
  );
  return { busy, run };
}

export function useCreateHub(): { creating: boolean; create: (input: HubCreateInput) => Promise<HubCreated> } {
  const { busy, run } = useBusy(hubConnectorService.createHub);
  return { creating: busy, create: run };
}

export function useCreateHubKey(hubId: string): { creating: boolean; create: (name: string) => Promise<ApiKeyCreated> } {
  const create = useCallback((name: string) => hubConnectorService.createKey(hubId, name), [hubId]);
  const { busy, run } = useBusy(create);
  return { creating: busy, create: run };
}

/** Run one CRM stock sync now. */
export function useSyncNow(): { syncing: boolean; sync: () => Promise<SyncState> } {
  const { busy, run } = useBusy(hubConnectorService.syncNow);
  return { syncing: busy, sync: run };
}

export interface UseHubResult {
  hub: Hub | null;
  isLoading: boolean;
  notFound: boolean;
  reload: () => void;
}

/** One hub. */
export function useHub(hubId: string): UseHubResult {
  const [hub, setHub] = useState<Hub | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [notFound, setNotFound] = useState(false);
  const [reloadKey, setReloadKey] = useState(0);
  const reload = useCallback(() => setReloadKey((k) => k + 1), []);

  useEffect(() => {
    let cancelled = false;
    hubConnectorService
      .getHub(hubId)
      .then((row) => {
        if (cancelled) return;
        setHub(row);
        setNotFound(false);
      })
      .catch(() => {
        if (!cancelled) setNotFound(true);
      })
      .finally(() => {
        if (!cancelled) setIsLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [hubId, reloadKey]);

  return { hub, isLoading, notFound, reload };
}

/** Picker options for locations / brands (loaded whole when the dialog opens). */
export function useHubOptions(kind: OptionKind, enabled: boolean): Option[] {
  const [options, setOptions] = useState<Option[]>([]);
  useEffect(() => {
    if (!enabled) return;
    let cancelled = false;
    hubConnectorService
      .listOptions(kind)
      .then((rows) => {
        if (!cancelled) setOptions(rows);
      })
      .catch(() => {
        if (!cancelled) setOptions([]);
      });
    return () => {
      cancelled = true;
    };
  }, [kind, enabled]);
  return options;
}
