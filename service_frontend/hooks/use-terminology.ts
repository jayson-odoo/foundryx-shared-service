'use client';

import { useCallback, useEffect, useState, useSyncExternalStore } from 'react';
import type { TermCatalogItem, TermLabels, TerminologyMap } from '@/types/terminology';
import { terminologyService } from '@/services/terminology-service';

/**
 * Terminology hooks (sprint-3/08, F10).
 *
 * `useTerminology()` - the single resolver every relabelable surface uses.
 * `label('form')` → "Survey", `labelPlural('form')` → "Surveys",
 * `t('form', count)` → count-aware. Missing key falls back to a humanized form
 * of the key (never blank - D7). Fetch-once module store (mirrors branding);
 * an override edit calls `refreshTerminology()` so every surface updates with
 * NO reload / re-login (D6).
 *
 * `useTerminologyAdmin()` - the settings-page catalog + set/reset.
 */

/* ─────────────── merged-map store (consumption surfaces) ─────────────── */

type MapState = { map: TerminologyMap | null };

let state: MapState = { map: null };
let promise: Promise<void> | null = null;
const listeners = new Set<() => void>();

function emit(): void {
  listeners.forEach((l) => l());
}

function fetchTerminology(): Promise<void> {
  promise ??= terminologyService
    .getTerminology()
    .then((map) => {
      state = { map };
    })
    .catch(() => {
      // Degrade to humanized fallbacks - never block render.
      state = { map: state.map ?? {} };
    })
    .finally(() => {
      promise = null;
      emit();
    });
  return promise;
}

/** Re-pull labels after an override mutation (instant in-session update). */
export function refreshTerminology(): Promise<void> {
  state = { map: state.map };
  promise = null;
  return fetchTerminology();
}

function subscribe(listener: () => void): () => void {
  listeners.add(listener);
  if (state.map === null) void fetchTerminology();
  return () => listeners.delete(listener);
}

const getSnapshot = (): MapState => state;
const getServerSnapshot = (): MapState => ({ map: null });

/** "event_type" → "Event Type". The never-blank fallback (D7). */
export function humanize(key: string): string {
  return key
    .split(/[_.\s-]+/)
    .filter(Boolean)
    .map((p) => p.charAt(0).toUpperCase() + p.slice(1))
    .join(' ');
}

export interface UseTerminologyResult {
  /** True once the first fetch resolved. */
  ready: boolean;
  /** Singular display label for an entity key. */
  label(key: string): string;
  /** Plural display label for an entity key. */
  labelPlural(key: string): string;
  /** Count-aware label: count === 1 → singular, else plural. */
  t(key: string, count: number): string;
  refetch(): Promise<void>;
}

export function useTerminology(): UseTerminologyResult {
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

  return { ready: map !== null, label, labelPlural, t, refetch: refreshTerminology };
}

/* ────────────────────────── admin (settings) hook ────────────────────────── */

export interface UseTerminologyAdminResult {
  catalog: TermCatalogItem[];
  isLoading: boolean;
  error: string | null;
  setTerm(key: string, labels: TermLabels): Promise<void>;
  resetTerm(key: string): Promise<void>;
  reload(): void;
}

export function useTerminologyAdmin(): UseTerminologyAdminResult {
  const [catalog, setCatalog] = useState<TermCatalogItem[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [nonce, setNonce] = useState(0);

  useEffect(() => {
    let active = true;
    setIsLoading(true);
    setError(null);
    terminologyService
      .getCatalog()
      .then((c) => active && setCatalog(c))
      .catch(
        (e) =>
          active &&
          setError(e instanceof Error ? e.message : 'Could not load terminology.'),
      )
      .finally(() => active && setIsLoading(false));
    return () => {
      active = false;
    };
  }, [nonce]);

  const reload = useCallback(() => setNonce((n) => n + 1), []);

  const setTerm = useCallback(async (key: string, labels: TermLabels) => {
    await terminologyService.setTerm(key, labels);
    await refreshTerminology(); // every surface follows immediately
    setNonce((n) => n + 1);
  }, []);

  const resetTerm = useCallback(async (key: string) => {
    await terminologyService.resetTerm(key);
    await refreshTerminology();
    setNonce((n) => n + 1);
  }, []);

  return { catalog, isLoading, error, setTerm, resetTerm, reload };
}
