'use client';

/**
 * The Foundryx UIUX list's remembered choices (playbook 0.71.0 "Lists": the
 * view toggle and each view's columns are "remembered per table"): which view
 * is chosen, whether the two views keep the same columns, and each view's
 * column order and hidden columns.
 *
 * Stored through the same per-user preferences the legacy list uses, under
 * new keys next to the list's own, so the switch-off list's saved columns are
 * never touched:
 * - `<viewKey>:fx`        `order` carries `view=<smart|table|card>` and `same`
 * - `<viewKey>:fx:smart`  Smart view columns (`order`, `hidden`)
 * - `<viewKey>:fx:table`  Table view columns (`order`, `hidden`)
 * The stored shape is the existing `ViewPreferences` one, so the backend
 * needs no change.
 */
import { useCallback, useEffect, useRef, useState } from 'react';
import type { ViewPreferences } from '@/types/resource';
import { preferencesService } from '@/services/preferences-service';

export type FxListView = 'smart' | 'table' | 'card';
export type FxColumnsView = 'smart' | 'table';

export interface FxViewColumns {
  order: string[];
  hidden: string[];
}

export interface FxListPrefs {
  isLoaded: boolean;
  view: FxListView;
  /** "Apply the same to ..." ticked: both views share one column set. */
  same: boolean;
  columns: Record<FxColumnsView, FxViewColumns>;
  setView: (view: FxListView) => void;
  setSame: (same: boolean, from: FxColumnsView) => void;
  setColumns: (view: FxColumnsView, next: FxViewColumns) => void;
}

const EMPTY: FxViewColumns = { order: [], hidden: [] };

function readMeta(prefs: ViewPreferences | null): { view?: FxListView; same: boolean } {
  const tokens = prefs?.order ?? [];
  const viewToken = tokens.find((t) => t.startsWith('view='))?.slice(5);
  const view =
    viewToken === 'smart' || viewToken === 'table' || viewToken === 'card'
      ? viewToken
      : undefined;
  return { view, same: tokens.includes('same') };
}

function readColumns(prefs: ViewPreferences | null): FxViewColumns | null {
  if (!prefs) return null;
  return { order: prefs.order ?? [], hidden: prefs.hidden ?? [] };
}

export function useFxListPrefs(
  viewKey: string,
  defaults: { view: FxListView; columns: FxViewColumns },
): FxListPrefs {
  const [isLoaded, setIsLoaded] = useState(false);
  const [view, setViewState] = useState<FxListView>(defaults.view);
  const [same, setSameState] = useState(false);
  const [columns, setColumnsState] = useState<Record<FxColumnsView, FxViewColumns>>({
    smart: EMPTY,
    table: EMPTY,
  });
  const timers = useRef<Record<string, ReturnType<typeof setTimeout>>>({});
  const defaultsRef = useRef(defaults);
  defaultsRef.current = defaults;

  useEffect(() => {
    let active = true;
    Promise.all([
      preferencesService.get(`${viewKey}:fx`),
      preferencesService.get(`${viewKey}:fx:smart`),
      preferencesService.get(`${viewKey}:fx:table`),
    ]).then(([meta, smart, table]) => {
      if (!active) return;
      const m = readMeta(meta);
      setViewState(m.view ?? defaultsRef.current.view);
      setSameState(m.same);
      setColumnsState({
        smart: readColumns(smart) ?? defaultsRef.current.columns,
        table: readColumns(table) ?? defaultsRef.current.columns,
      });
      setIsLoaded(true);
    });
    return () => {
      active = false;
    };
  }, [viewKey]);

  useEffect(
    () => () => {
      Object.values(timers.current).forEach(clearTimeout);
    },
    [],
  );

  const save = useCallback(
    (key: string, prefs: ViewPreferences) => {
      clearTimeout(timers.current[key]);
      timers.current[key] = setTimeout(() => {
        void preferencesService.save(key, prefs);
      }, 400);
    },
    [],
  );

  const saveMeta = useCallback(
    (v: FxListView, s: boolean) =>
      save(`${viewKey}:fx`, { order: [`view=${v}`, ...(s ? ['same'] : [])], widths: {}, hidden: [] }),
    [save, viewKey],
  );

  const saveColumns = useCallback(
    (v: FxColumnsView, c: FxViewColumns) =>
      save(`${viewKey}:fx:${v}`, { order: c.order, widths: {}, hidden: c.hidden }),
    [save, viewKey],
  );

  const setView = useCallback(
    (next: FxListView) => {
      setViewState(next);
      saveMeta(next, same);
    },
    [saveMeta, same],
  );

  const setSame = useCallback(
    (next: boolean, from: FxColumnsView) => {
      setSameState(next);
      saveMeta(view, next);
      if (!next) return;
      // Ticking copies this view's columns to the other one.
      const other: FxColumnsView = from === 'smart' ? 'table' : 'smart';
      setColumnsState((prev) => {
        saveColumns(other, prev[from]);
        return { ...prev, [other]: prev[from] };
      });
    },
    [saveColumns, saveMeta, view],
  );

  const setColumns = useCallback(
    (target: FxColumnsView, next: FxViewColumns) => {
      setColumnsState((prev) => {
        const out = { ...prev, [target]: next };
        saveColumns(target, next);
        if (same) {
          const other: FxColumnsView = target === 'smart' ? 'table' : 'smart';
          out[other] = next;
          saveColumns(other, next);
        }
        return out;
      });
    },
    [same, saveColumns],
  );

  return { isLoaded, view, same, columns, setView, setSame, setColumns };
}
