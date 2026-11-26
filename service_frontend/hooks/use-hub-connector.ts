'use client';

import { useCallback, useEffect, useRef, useState } from 'react';
import { ApiError } from '@/lib/api-client';
import { hubConnectorService } from '@/services/hub-connector-service';
import type {
  ApiKeyCreated,
  Hub,
  HubCreateInput,
  HubCreated,
  Option,
  OptionKind,
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

export function useCreateHubKey(): { creating: boolean; create: (name: string) => Promise<ApiKeyCreated> } {
  const { busy, run } = useBusy(hubConnectorService.createKey);
  return { creating: busy, create: run };
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

/** Customer picker: searched on the server as the user types (debounced). */
export function useCustomerSearch(enabled: boolean): { options: Option[]; setQuery: (q: string) => void } {
  const [options, setOptions] = useState<Option[]>([]);
  const [query, setQuery] = useState('');
  const seq = useRef(0);

  useEffect(() => {
    if (!enabled) return;
    const mine = ++seq.current;
    const timer = setTimeout(() => {
      hubConnectorService
        .listOptions('customers', query)
        .then((rows) => {
          if (seq.current === mine) setOptions(rows);
        })
        .catch(() => {
          if (seq.current === mine) setOptions([]);
        });
    }, query ? 250 : 0);
    return () => clearTimeout(timer);
  }, [query, enabled]);

  return { options, setQuery };
}
