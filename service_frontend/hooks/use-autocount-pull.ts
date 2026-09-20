'use client';

import { useCallback, useEffect, useRef, useState } from 'react';
import { ApiError } from '@/lib/api-client';
import { readFieldErrors } from '@/lib/autocount-etl';
import { autocountService } from '@/services/autocount-service';
import type {
  AutocountCompany,
  AutocountDeliveryMode,
  AutocountEntityConfig,
  AutocountPullApiKeyCreateInput,
  AutocountPullApiKeyIssued,
  AutocountPullSnapshot,
  AutocountPullSnapshotRowsPage,
} from '@/types/autocount';

/**
 * Human-invoked pull hooks (sprint-5/10, S2) - the hook boundary the task
 * editor's Schedule tab and the `/autocount/pull` surfaces talk to
 * (`UI -> hook -> service -> api-client`). Components never call the
 * service directly (a `ResourceListConfig`'s own `fetcher` is the
 * established exception - it IS the hook layer for a list, same as every
 * other AutoCount list config).
 */

// ── delivery mode (AC-10-11/16) ───────────────────────────────────────────────

export interface UseSetDeliveryModeResult {
  saving: boolean;
  error: string | null;
  fieldErrors: Record<string, string>;
  save: (
    companyId: string,
    entityType: string,
    deliveryMode: AutocountDeliveryMode,
  ) => Promise<AutocountEntityConfig | null>;
  clearError: () => void;
}

/** The Schedule tab's delivery toggle save (AC-10-11) - a standalone PUT,
 * separate from the task's own source-config save (the switch touches
 * neither `sourceConfig` nor `resultColumns`/`ac_row_hash`). */
export function useSetDeliveryMode(): UseSetDeliveryModeResult {
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [fieldErrors, setFieldErrors] = useState<Record<string, string>>({});

  const save = useCallback(
    async (
      companyId: string,
      entityType: string,
      deliveryMode: AutocountDeliveryMode,
    ): Promise<AutocountEntityConfig | null> => {
      setSaving(true);
      setError(null);
      setFieldErrors({});
      try {
        return await autocountService.setDeliveryMode(companyId, entityType, deliveryMode);
      } catch (e) {
        if (e instanceof ApiError) {
          setError(e.message);
          setFieldErrors(readFieldErrors(e.detail));
        } else {
          setError('The delivery mode could not be saved.');
        }
        return null;
      } finally {
        setSaving(false);
      }
    },
    [],
  );

  const clearError = useCallback(() => {
    setError(null);
    setFieldErrors({});
  }, []);

  return { saving, error, fieldErrors, save, clearError };
}

// ── column probe (AC-10-05 companion) ─────────────────────────────────────────

export interface UsePreviewColumnsMapResult {
  /** Column names by caller-chosen key (the Lookups editor keys by row id -
   * rows are added/removed/reordered, so a single-slot hook cannot track
   * more than one row's own Test at a time). */
  columnsByKey: Record<string, string[]>;
  loadingKeys: Record<string, boolean>;
  errorsByKey: Record<string, string>;
  /** Probe an endpoint's page-1 column names under `key`. Never throws. */
  run: (key: string, connectionId: string, path: string) => Promise<string[]>;
}

/** The Lookups editor's own per-row remote-column probe (AC-10-05) - the
 * join/field pickers offer REAL columns, never free text. */
export function usePreviewColumnsMap(): UsePreviewColumnsMapResult {
  const [columnsByKey, setColumnsByKey] = useState<Record<string, string[]>>({});
  const [loadingKeys, setLoadingKeys] = useState<Record<string, boolean>>({});
  const [errorsByKey, setErrorsByKey] = useState<Record<string, string>>({});

  const run = useCallback(async (key: string, connectionId: string, path: string): Promise<string[]> => {
    setLoadingKeys((prev) => ({ ...prev, [key]: true }));
    setErrorsByKey((prev) => {
      const next = { ...prev };
      delete next[key];
      return next;
    });
    try {
      const result = await autocountService.previewColumns(connectionId, path);
      setColumnsByKey((prev) => ({ ...prev, [key]: result }));
      return result;
    } catch (e) {
      setErrorsByKey((prev) => ({
        ...prev,
        [key]: e instanceof ApiError ? e.message : 'The endpoint could not be reached.',
      }));
      return [];
    } finally {
      setLoadingKeys((prev) => ({ ...prev, [key]: false }));
    }
  }, []);

  return { columnsByKey, loadingKeys, errorsByKey, run };
}

// ── companies (Issue-key / Build-snapshot dialogs) ────────────────────────────

export interface UseAutocountCompaniesResult {
  companies: AutocountCompany[];
  isLoading: boolean;
}

/** Every company of the tenant, unpaginated (a small list) - the Issue-key
 * dialog's company `MultiSelect` and the Build-snapshot dialog's company
 * picker. */
export function useAutocountCompanies(): UseAutocountCompaniesResult {
  const [companies, setCompanies] = useState<AutocountCompany[]>([]);
  const [isLoading, setIsLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    autocountService
      .listCompanies({ page: 0, pageSize: 200 })
      .then((result) => {
        if (!cancelled) setCompanies(result.data);
      })
      .catch(() => {
        if (!cancelled) setCompanies([]);
      })
      .finally(() => {
        if (!cancelled) setIsLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  return { companies, isLoading };
}

// ── pull API keys (AC-10-28/37/38) ────────────────────────────────────────────

export interface UseIssuePullKeyResult {
  issuing: boolean;
  error: string | null;
  fieldErrors: Record<string, string>;
  issue: (input: AutocountPullApiKeyCreateInput) => Promise<AutocountPullApiKeyIssued | null>;
  reset: () => void;
}

/** Issue-key dialog (AC-10-38) - the plaintext is read off the resolved
 * value exactly once; nothing here persists it beyond the caller's own
 * render. */
export function useIssuePullKey(): UseIssuePullKeyResult {
  const [issuing, setIssuing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [fieldErrors, setFieldErrors] = useState<Record<string, string>>({});

  const issue = useCallback(
    async (input: AutocountPullApiKeyCreateInput): Promise<AutocountPullApiKeyIssued | null> => {
      setIssuing(true);
      setError(null);
      setFieldErrors({});
      try {
        return await autocountService.issuePullKey(input);
      } catch (e) {
        if (e instanceof ApiError) {
          setError(e.message);
          setFieldErrors(readFieldErrors(e.detail));
        } else {
          setError('The key could not be issued.');
        }
        return null;
      } finally {
        setIssuing(false);
      }
    },
    [],
  );

  const reset = useCallback(() => {
    setError(null);
    setFieldErrors({});
  }, []);

  return { issuing, error, fieldErrors, issue, reset };
}

// ── snapshots (AC-10-37/49) ───────────────────────────────────────────────────

export interface UseBuildPullSnapshotResult {
  building: boolean;
  error: string | null;
  build: (companyId: string, entityType: string) => Promise<AutocountPullSnapshot | null>;
  reset: () => void;
}

/** Build-snapshot dialog (AC-10-37) - re-attaches to an in-flight build for
 * the same (company, entity) rather than starting a second one (AC-10-26). */
export function useBuildPullSnapshot(): UseBuildPullSnapshotResult {
  const [building, setBuilding] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const build = useCallback(
    async (companyId: string, entityType: string): Promise<AutocountPullSnapshot | null> => {
      setBuilding(true);
      setError(null);
      try {
        return await autocountService.buildPullSnapshot(companyId, entityType);
      } catch (e) {
        setError(e instanceof ApiError ? e.message : 'The snapshot could not be built.');
        return null;
      } finally {
        setBuilding(false);
      }
    },
    [],
  );

  const reset = useCallback(() => setError(null), []);

  return { building, error, build, reset };
}

export type PullSnapshotDetailState =
  | { status: 'loading' }
  | { status: 'notFound' }
  | { status: 'error'; message: string }
  | { status: 'ready'; snapshot: AutocountPullSnapshot };

export interface UsePullSnapshotDetailResult {
  state: PullSnapshotDetailState;
  reload: () => void;
}

/** Snapshot detail header (AC-10-49) - polls while `building` (a build has
 * no short server-side timeout, AC-10-86), stops once `ready`/`failed`. */
export function usePullSnapshotDetail(id: string): UsePullSnapshotDetailResult {
  const [state, setState] = useState<PullSnapshotDetailState>({ status: 'loading' });
  const [reloadKey, setReloadKey] = useState(0);
  const reload = useCallback(() => setReloadKey((k) => k + 1), []);

  useEffect(() => {
    let cancelled = false;
    let timer: ReturnType<typeof setTimeout> | null = null;

    async function poll(): Promise<void> {
      try {
        const snapshot = await autocountService.getPullSnapshot(id);
        if (cancelled) return;
        setState({ status: 'ready', snapshot });
        if (snapshot.status === 'building') {
          timer = setTimeout(() => void poll(), 3000);
        }
      } catch (e) {
        if (cancelled) return;
        if (e instanceof ApiError && e.status === 404) {
          setState({ status: 'notFound' });
          return;
        }
        setState({
          status: 'error',
          message: e instanceof ApiError ? e.message : 'The snapshot could not be loaded.',
        });
      }
    }

    setState({ status: 'loading' });
    void poll();
    return () => {
      cancelled = true;
      if (timer) clearTimeout(timer);
    };
  }, [id, reloadKey]);

  return { state, reload };
}

export type PullSnapshotRowsState =
  | { status: 'idle' }
  | { status: 'loading' }
  | { status: 'error'; message: string }
  | { status: 'success'; page: AutocountPullSnapshotRowsPage };

export interface UsePullSnapshotRowsResult {
  state: PullSnapshotRowsState;
  /** `page` is 0-based, matching every other list in this app. */
  run: (page?: number, pageSize?: number) => Promise<void>;
}

/** The first page of a snapshot's rows (AC-10-49), reused with the existing
 * preview-grid primitive. */
export function usePullSnapshotRows(id: string): UsePullSnapshotRowsResult {
  const [state, setState] = useState<PullSnapshotRowsState>({ status: 'idle' });
  const runId = useRef(0);

  const run = useCallback(
    async (page = 0, pageSize = 1000): Promise<void> => {
      const current = ++runId.current;
      setState({ status: 'loading' });
      try {
        const result = await autocountService.getPullSnapshotRows(id, page, pageSize);
        if (current !== runId.current) return;
        setState({ status: 'success', page: result });
      } catch (e) {
        if (current !== runId.current) return;
        setState({
          status: 'error',
          message: e instanceof ApiError ? e.message : 'The rows could not be loaded.',
        });
      }
    },
    [id],
  );

  return { state, run };
}
