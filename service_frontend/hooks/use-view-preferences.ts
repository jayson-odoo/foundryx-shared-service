'use client';

import { useCallback, useEffect, useRef, useState } from 'react';
import type {
  ColumnOrderState,
  ColumnSizingState,
  OnChangeFn,
  Updater,
  VisibilityState,
} from '@tanstack/react-table';
import type { ViewPreferences } from '@/types/resource';
import { preferencesService } from '@/services/preferences-service';

export interface UseViewPreferencesResult {
  isLoaded: boolean;
  columnOrder: ColumnOrderState;
  columnVisibility: VisibilityState;
  columnSizing: ColumnSizingState;
  setColumnOrder: OnChangeFn<ColumnOrderState>;
  setColumnVisibility: OnChangeFn<VisibilityState>;
  setColumnSizing: OnChangeFn<ColumnSizingState>;
}

function applyUpdater<T>(updater: Updater<T>, prev: T): T {
  return typeof updater === 'function' ? (updater as (old: T) => T)(prev) : updater;
}

/**
 * Loads + persists per-user column prefs (order / visibility / width) for a
 * `viewKey`, returning controlled state for TanStack Table. Saves are debounced.
 * Persistence goes through `preferences-service` (backend user_view_preferences).
 */
export function useViewPreferences(viewKey: string): UseViewPreferencesResult {
  const [isLoaded, setIsLoaded] = useState(false);
  const [columnOrder, setOrder] = useState<ColumnOrderState>([]);
  const [columnVisibility, setVisibility] = useState<VisibilityState>({});
  const [columnSizing, setSizing] = useState<ColumnSizingState>({});
  const saveTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  // Load once on mount.
  useEffect(() => {
    let active = true;
    preferencesService.get(viewKey).then((prefs) => {
      if (!active) return;
      if (prefs) {
        setOrder(prefs.order ?? []);
        setSizing(prefs.widths ?? {});
        setVisibility(Object.fromEntries((prefs.hidden ?? []).map((id) => [id, false])));
      }
      setIsLoaded(true);
    });
    return () => {
      active = false;
    };
  }, [viewKey]);

  // Debounced persist on any change (after initial load).
  const persist = useCallback(
    (order: ColumnOrderState, visibility: VisibilityState, sizing: ColumnSizingState) => {
      if (saveTimer.current) clearTimeout(saveTimer.current);
      saveTimer.current = setTimeout(() => {
        const prefs: ViewPreferences = {
          order,
          widths: sizing,
          hidden: Object.entries(visibility)
            .filter(([, visible]) => visible === false)
            .map(([id]) => id),
        };
        void preferencesService.save(viewKey, prefs);
      }, 400);
    },
    [viewKey],
  );

  const setColumnOrder = useCallback<OnChangeFn<ColumnOrderState>>(
    (updater) =>
      setOrder((prev) => {
        const next = applyUpdater(updater, prev);
        if (isLoaded) persist(next, columnVisibility, columnSizing);
        return next;
      }),
    [isLoaded, persist, columnVisibility, columnSizing],
  );

  const setColumnVisibility = useCallback<OnChangeFn<VisibilityState>>(
    (updater) =>
      setVisibility((prev) => {
        const next = applyUpdater(updater, prev);
        if (isLoaded) persist(columnOrder, next, columnSizing);
        return next;
      }),
    [isLoaded, persist, columnOrder, columnSizing],
  );

  const setColumnSizing = useCallback<OnChangeFn<ColumnSizingState>>(
    (updater) =>
      setSizing((prev) => {
        const next = applyUpdater(updater, prev);
        if (isLoaded) persist(columnOrder, columnVisibility, next);
        return next;
      }),
    [isLoaded, persist, columnOrder, columnVisibility],
  );

  return {
    isLoaded,
    columnOrder,
    columnVisibility,
    columnSizing,
    setColumnOrder,
    setColumnVisibility,
    setColumnSizing,
  };
}
