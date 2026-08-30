'use client';

import { useCallback, useEffect, useRef, useState } from 'react';
import { ApiError } from '@/lib/api-client';
import { autocountService } from '@/services/autocount-service';
import type {
  AutocountEtlSourceConfig,
  AutocountEtlTask,
  AutocountSqlConnection,
  AutocountSqlPreview,
  AutocountSqlSchema,
} from '@/types/autocount';

/**
 * Direct-DB ETL hooks (plan 22 S1) - the hook boundary the task editor talks
 * to (`UI → hook → service → api-client`). Components never call the service.
 */

// ── task ─────────────────────────────────────────────────────────────────────

export interface UseAutocountEtlTaskResult {
  task: AutocountEtlTask | null;
  isLoading: boolean;
  notFound: boolean;
  /** Last save error, surfaced inline. Cleared on a fresh save. */
  saveError: string | null;
  /** Per-field 422 errors from the save-time guard (AC-22-11). */
  fieldErrors: Record<string, string>;
  isSaving: boolean;
  /** Draft-save the source config. False (with `saveError`) on rejection. */
  save: (sourceConfig: AutocountEtlSourceConfig) => Promise<boolean>;
  reload: () => void;
}

function readFieldErrors(detail: unknown): Record<string, string> {
  if (!detail || typeof detail !== 'object') return {};
  const bag = (detail as { fieldErrors?: unknown }).fieldErrors;
  if (!bag || typeof bag !== 'object') return {};
  const out: Record<string, string> = {};
  for (const [key, value] of Object.entries(bag as Record<string, unknown>)) {
    if (typeof value === 'string') out[key] = value;
  }
  return out;
}

export function useAutocountEtlTask(
  companyId: string,
  entityType: string,
): UseAutocountEtlTaskResult {
  const [task, setTask] = useState<AutocountEtlTask | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [notFound, setNotFound] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);
  const [fieldErrors, setFieldErrors] = useState<Record<string, string>>({});
  const [isSaving, setIsSaving] = useState(false);
  const [reloadKey, setReloadKey] = useState(0);

  const reload = useCallback(() => setReloadKey((k) => k + 1), []);

  useEffect(() => {
    let cancelled = false;
    setIsLoading(true);
    setNotFound(false);
    autocountService
      .getEtlTask(companyId, entityType)
      .then((loaded) => {
        if (!cancelled) setTask(loaded);
      })
      .catch((error: unknown) => {
        if (cancelled) return;
        if (error instanceof ApiError && error.status === 404) setNotFound(true);
        else setTask(null);
      })
      .finally(() => {
        if (!cancelled) setIsLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [companyId, entityType, reloadKey]);

  const save = useCallback(
    async (sourceConfig: AutocountEtlSourceConfig): Promise<boolean> => {
      setIsSaving(true);
      setSaveError(null);
      setFieldErrors({});
      try {
        const saved = await autocountService.updateEtlTask(companyId, entityType, {
          sourceConfig,
        });
        setTask(saved);
        return true;
      } catch (error) {
        if (error instanceof ApiError) {
          setSaveError(error.message);
          setFieldErrors(readFieldErrors(error.detail));
        } else {
          setSaveError('The task could not be saved.');
        }
        return false;
      } finally {
        setIsSaving(false);
      }
    },
    [companyId, entityType],
  );

  return { task, isLoading, notFound, saveError, fieldErrors, isSaving, save, reload };
}

// ── connections ──────────────────────────────────────────────────────────────

export interface UseAutocountSqlConnectionsResult {
  connections: AutocountSqlConnection[];
  isLoading: boolean;
  error: string | null;
}

/** The tenant's SQL-database connections - the ONLY valid picker options. */
export function useAutocountSqlConnections(): UseAutocountSqlConnectionsResult {
  const [connections, setConnections] = useState<AutocountSqlConnection[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    autocountService
      .listSqlConnections()
      .then((list) => {
        if (!cancelled) setConnections(list);
      })
      .catch((e: unknown) => {
        if (!cancelled) {
          setError(e instanceof ApiError ? e.message : 'Connections could not be loaded.');
        }
      })
      .finally(() => {
        if (!cancelled) setIsLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  return { connections, isLoading, error };
}

// ── schema ───────────────────────────────────────────────────────────────────

export interface UseAutocountSqlSchemaResult {
  schema: AutocountSqlSchema | null;
  isLoading: boolean;
  /** Sanitized connect/introspection failure (never a DSN or credential). */
  error: string | null;
  /** Bust the server-side cache and re-introspect (AC-22-05). */
  refresh: () => void;
}

/** The cached schema tree for one connection; null connection = idle. */
export function useAutocountSqlSchema(
  connectionId: string | null,
): UseAutocountSqlSchemaResult {
  const [schema, setSchema] = useState<AutocountSqlSchema | null>(null);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [refreshKey, setRefreshKey] = useState(0);
  // The first load per connection uses the cache; an explicit Refresh busts it.
  const forceRefresh = useRef(false);

  const refresh = useCallback(() => {
    forceRefresh.current = true;
    setRefreshKey((k) => k + 1);
  }, []);

  useEffect(() => {
    if (!connectionId) {
      setSchema(null);
      setError(null);
      setIsLoading(false);
      return;
    }
    let cancelled = false;
    const wantRefresh = forceRefresh.current;
    forceRefresh.current = false;
    setIsLoading(true);
    setError(null);
    autocountService
      .getSqlSchema(connectionId, wantRefresh ? { refresh: true } : undefined)
      .then((loaded) => {
        if (!cancelled) setSchema(loaded);
      })
      .catch((e: unknown) => {
        if (cancelled) return;
        setSchema(null);
        setError(e instanceof ApiError ? e.message : 'The schema could not be loaded.');
      })
      .finally(() => {
        if (!cancelled) setIsLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [connectionId, refreshKey]);

  return { schema, isLoading, error, refresh };
}

// ── preview ──────────────────────────────────────────────────────────────────

/** The four designed preview states (AC-22-07) - `success` covers 0 rows. */
export type SqlPreviewState =
  | { status: 'idle' }
  | { status: 'loading' }
  | { status: 'error'; message: string }
  | { status: 'success'; preview: AutocountSqlPreview };

export interface UseSqlPreviewResult {
  state: SqlPreviewState;
  /** Run the candidate SELECT (≤ 100 rows). Never throws - errors land in state. */
  run: (connectionId: string, query: string) => Promise<void>;
  reset: () => void;
}

export function useSqlPreview(): UseSqlPreviewResult {
  const [state, setState] = useState<SqlPreviewState>({ status: 'idle' });
  // Only the LATEST run may settle state - a slow earlier preview must not
  // overwrite a newer result.
  const runId = useRef(0);

  const run = useCallback(async (connectionId: string, query: string) => {
    const id = ++runId.current;
    setState({ status: 'loading' });
    try {
      const preview = await autocountService.previewSqlQuery(connectionId, query);
      if (id === runId.current) setState({ status: 'success', preview });
    } catch (e) {
      if (id !== runId.current) return;
      setState({
        status: 'error',
        message: e instanceof ApiError ? e.message : 'The preview could not be run.',
      });
    }
  }, []);

  const reset = useCallback(() => {
    runId.current += 1;
    setState({ status: 'idle' });
  }, []);

  return { state, run, reset };
}
