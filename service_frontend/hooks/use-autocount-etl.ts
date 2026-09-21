'use client';

import { useCallback, useEffect, useRef, useState } from 'react';
import { ApiError } from '@/lib/api-client';
import { readFieldErrors, readTaskError } from '@/lib/autocount-etl';
import { autocountService } from '@/services/autocount-service';
import type {
  AutocountApiConnection,
  AutocountCombineConfig,
  AutocountEtlSourceConfig,
  AutocountEtlTask,
  AutocountEtlTaskError,
  AutocountLookupSpec,
  AutocountPreview,
  AutocountSqlConnection,
  AutocountSqlPreview,
  AutocountSqlSchema,
  HttpPreview,
} from '@/types/autocount';

/**
 * sprint-5/11 (AC-11-20..27) - the Cloudflare-safe non-blocking preview: a
 * job round-trip replaces the old single blocking request. Poll cadence is
 * short and deterministic against the mock (no fake timers needed).
 */
const PREVIEW_JOB_POLL_MS = 200;

function pause(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

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
  /**
   * Draft-save the source config. `sourceImpl` (sprint-5/08, D13) - present
   * when the Source tab's toggle derives `sql_db`/`autocount_http`; omitted
   * for a `sql_db`-only caller that predates the toggle. False (with
   * `saveError`) on rejection.
   */
  save: (
    sourceConfig: AutocountEtlSourceConfig,
    sourceImpl?: 'sql_db' | 'autocount_http',
  ) => Promise<boolean>;
  /** Adopt a task returned by a lifecycle call (activate/pause/resume/run/preview). */
  apply: (task: AutocountEtlTask) => void;
  reload: () => void;
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
    async (
      sourceConfig: AutocountEtlSourceConfig,
      sourceImpl?: 'sql_db' | 'autocount_http',
    ): Promise<boolean> => {
      setIsSaving(true);
      setSaveError(null);
      setFieldErrors({});
      try {
        const saved = await autocountService.updateEtlTask(companyId, entityType, {
          sourceConfig,
          ...(sourceImpl ? { sourceImpl } : {}),
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

  const apply = useCallback((next: AutocountEtlTask) => setTask(next), []);

  return { task, isLoading, notFound, saveError, fieldErrors, isSaving, save, apply, reload };
}

// ── activation gate (plan 22 S2, AC-22-18, Appendix A6) ──────────────────────

/**
 * The dry-run states the Review & Activate tab designs: `error` is the dry
 * run itself failing (502 - Activate stays withheld), `taskError` is a Sorento
 * anchor 422 - a TASK-level configuration error (fix the company code), never
 * a per-record failure. `loading` rides the preview-job progress (sprint-5/11,
 * AC-11-27) - `stage`/`pagesDone`/`pagesTotal` are absent until known, never
 * guessed; `cancelling` is set once `cancel()` has been called but the job has
 * not yet reported the terminal state.
 */
export type EtlPreviewState =
  | { status: 'idle' }
  | {
      status: 'loading';
      stage?: string | null;
      pagesDone?: number | null;
      pagesTotal?: number | null;
      cancelling?: boolean;
    }
  | { status: 'error'; message: string }
  | { status: 'taskError'; error: AutocountEtlTaskError }
  | { status: 'success'; preview: AutocountPreview };

export interface UseEtlTaskPreviewResult {
  state: EtlPreviewState;
  /** Run the initial-load dry run as a job (AC-11-22) - never awaits the
   * walk; resolves once the job reaches a terminal state. Never throws -
   * every outcome lands in state. */
  run: () => Promise<void>;
  /** Cooperative cancel of an in-flight job (AC-11-24) - a no-op while idle
   * or already terminal. */
  cancel: () => void;
  reset: () => void;
}

/**
 * sprint-5/11 (AC-11-20..27) - "Run preview" starts the `full`-scope
 * `autocount_source_preview` job instead of awaiting `preview_task`
 * directly, and polls `GET /autocount/previews/{jobId}` (AC-11-22) against
 * the real backend (S4). `initialJobId` (AC-11-23/27) re-attaches to an
 * already-in-flight job after a remount/reload (`task.previewJobId`) -
 * polled without a fresh `startPreviewJob` call.
 */
export function useEtlTaskPreview(
  companyId: string,
  entityType: string,
  onTask: (task: AutocountEtlTask) => void,
  initialJobId?: string | null,
): UseEtlTaskPreviewResult {
  const [state, setState] = useState<EtlPreviewState>({ status: 'idle' });
  const runId = useRef(0);
  const activeJobId = useRef<string | null>(null);
  const cancelRequested = useRef(false);
  const attachedJobIdRef = useRef<string | null>(null);

  const pollUntilTerminal = useCallback(
    async (jobId: string, id: number) => {
      for (;;) {
        const job = await autocountService.getPreviewJob(jobId);
        if (id !== runId.current) return;
        // AC-11-23 - the claim is ONE per task regardless of scope (a
        // `full` Run-preview job re-attach lands here too, via the SAME
        // `task.previewJobId`): a job that turns out to belong to the
        // OTHER scope was never THIS hook's own run - leave it idle,
        // never a fabricated error/success.
        if (job.scope !== 'full') {
          setState({ status: 'idle' });
          return;
        }
        if (job.status === 'queued' || job.status === 'running') {
          setState({
            status: 'loading',
            stage: job.progress?.stage ?? null,
            pagesDone: job.progress?.pagesDone ?? null,
            pagesTotal: job.progress?.pagesTotal ?? null,
            cancelling: cancelRequested.current,
          });
          await pause(PREVIEW_JOB_POLL_MS);
          continue;
        }
        if (job.status === 'cancelled') {
          setState({ status: 'idle' });
          return;
        }
        if (job.status === 'failed') {
          if (job.taskError) {
            setState({ status: 'taskError', error: job.taskError });
            return;
          }
          setState({ status: 'error', message: job.error ?? 'The dry run could not be completed.' });
          return;
        }
        // done
        if (job.result?.scope === 'full') {
          onTask(job.result.task);
          setState({ status: 'success', preview: job.result.preview });
          return;
        }
        setState({ status: 'error', message: 'The dry run could not be completed.' });
        return;
      }
    },
    [onTask],
  );

  const run = useCallback(async () => {
    const id = ++runId.current;
    cancelRequested.current = false;
    activeJobId.current = null;
    setState({ status: 'loading' });
    try {
      const started = await autocountService.startPreviewJob({ scope: 'full', companyId, entityType });
      if (id !== runId.current) return;
      activeJobId.current = started.jobId;
      attachedJobIdRef.current = started.jobId;
      await pollUntilTerminal(started.jobId, id);
    } catch (e) {
      if (id !== runId.current) return;
      const taskError = e instanceof ApiError && e.status === 422 ? readTaskError(e.detail) : null;
      if (taskError) {
        setState({ status: 'taskError', error: taskError });
        return;
      }
      setState({
        status: 'error',
        message: e instanceof ApiError ? e.message : 'The dry run could not be completed.',
      });
    }
  }, [companyId, entityType, pollUntilTerminal]);

  // AC-11-23/27 - re-attach to an already-in-flight job after a remount/
  // reload (`task.previewJobId`): a poll, never a fresh `startPreviewJob`
  // (which would start a SECOND walk the claim would just reject anyway).
  // Attaches once per job id - a re-render carrying the SAME id (the task
  // re-fetched while this hook is already polling it) is a no-op.
  useEffect(() => {
    if (!initialJobId || attachedJobIdRef.current === initialJobId) return;
    attachedJobIdRef.current = initialJobId;
    const id = ++runId.current;
    cancelRequested.current = false;
    activeJobId.current = initialJobId;
    setState({ status: 'loading' });
    void pollUntilTerminal(initialJobId, id);
  }, [initialJobId, pollUntilTerminal]);

  const cancel = useCallback(() => {
    if (!activeJobId.current) return;
    cancelRequested.current = true;
    void autocountService.cancelPreviewJob(activeJobId.current);
  }, []);

  const reset = useCallback(() => {
    runId.current += 1;
    cancelRequested.current = false;
    activeJobId.current = null;
    setState({ status: 'idle' });
  }, []);

  return { state, run, cancel, reset };
}

// ── lifecycle: activate / pause / resume / run now (AC-22-18/19) ──────────────

export type EtlLifecycleAction = 'activate' | 'pause' | 'resume' | 'run';

export interface UseEtlTaskLifecycleResult {
  /** The action in flight, if any (one at a time - the buttons disable together). */
  busy: EtlLifecycleAction | null;
  /** Last lifecycle failure (409s from the server-side gate), surfaced inline. */
  error: string | null;
  activate: () => Promise<boolean>;
  pause: () => Promise<boolean>;
  resume: () => Promise<boolean>;
  /** Manual run now; resolves to the run id (null on failure). */
  runNow: () => Promise<string | null>;
  clearError: () => void;
}

export function useEtlTaskLifecycle(
  companyId: string,
  entityType: string,
  onTask: (task: AutocountEtlTask) => void,
): UseEtlTaskLifecycleResult {
  const [busy, setBusy] = useState<EtlLifecycleAction | null>(null);
  const [error, setError] = useState<string | null>(null);

  const perform = useCallback(
    async (action: EtlLifecycleAction, call: () => Promise<AutocountEtlTask>): Promise<boolean> => {
      setBusy(action);
      setError(null);
      try {
        onTask(await call());
        return true;
      } catch (e) {
        setError(e instanceof ApiError ? e.message : 'That action could not be completed.');
        return false;
      } finally {
        setBusy(null);
      }
    },
    [onTask],
  );

  const activate = useCallback(
    () => perform('activate', () => autocountService.activateEtlTask(companyId, entityType)),
    [companyId, entityType, perform],
  );
  const pause = useCallback(
    () => perform('pause', () => autocountService.pauseEtlTask(companyId, entityType)),
    [companyId, entityType, perform],
  );
  const resume = useCallback(
    () => perform('resume', () => autocountService.resumeEtlTask(companyId, entityType)),
    [companyId, entityType, perform],
  );

  const runNow = useCallback(async (): Promise<string | null> => {
    let runId: string | null = null;
    await perform('run', async () => {
      const started = await autocountService.runEtlTaskNow(companyId, entityType);
      runId = started.runId;
      return started.task;
    });
    return runId;
  }, [companyId, entityType, perform]);

  const clearError = useCallback(() => setError(null), []);

  return { busy, error, activate, pause, resume, runNow, clearError };
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
  /**
   * Run the candidate SELECT (≤ 100 rows). Never throws - errors land in
   * state. `opts.bindDocKey` (plan 22 S5) - a document's `lineQuery` carries
   * a `:doc_key` bound param; `true` binds `opts.docKey` (a harmless sample,
   * or omitted for a NULL bind - just enough for the query to execute so its
   * columns can populate the line-column pickers).
   */
  run: (
    connectionId: string,
    query: string,
    opts?: { bindDocKey?: boolean; docKey?: string | null },
  ) => Promise<void>;
  reset: () => void;
}

export function useSqlPreview(): UseSqlPreviewResult {
  const [state, setState] = useState<SqlPreviewState>({ status: 'idle' });
  // Only the LATEST run may settle state - a slow earlier preview must not
  // overwrite a newer result.
  const runId = useRef(0);

  const run = useCallback(async (
    connectionId: string,
    query: string,
    opts?: { bindDocKey?: boolean; docKey?: string | null },
  ) => {
    const id = ++runId.current;
    setState({ status: 'loading' });
    try {
      const preview = await autocountService.previewSqlQuery(connectionId, query, opts);
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

/**
 * A one-shot line fetch, distinct from `useSqlPreview` (sprint-5/02,
 * AC-02-22): the Mapping tab's Simulate dialog picks ONE header preview row
 * and fetches ITS lines by re-running the line query bound to that row's
 * `:doc_key` - a separate call so it never disturbs the Query tab's own
 * line-preview state (used for column discovery, always NULL-bound).
 */
export function useLineFetcher(): {
  fetchLines: (connectionId: string, lineQuery: string, docKey: string) => Promise<AutocountSqlPreview>;
} {
  const fetchLines = useCallback(
    (connectionId: string, lineQuery: string, docKey: string) =>
      autocountService.previewSqlQuery(connectionId, lineQuery, { bindDocKey: true, docKey }),
    [],
  );
  return { fetchLines };
}

// ── open REST API source (sprint-5/08, S1) ────────────────────────────────────

export interface UseAutocountApiConnectionsResult {
  connections: AutocountApiConnection[];
  isLoading: boolean;
  error: string | null;
}

/** Every `autocount` connection of the tenant, badged by auth (AC-08-15) -
 * the Source tab's API-branch picker source. */
export function useAutocountApiConnections(): UseAutocountApiConnectionsResult {
  const [connections, setConnections] = useState<AutocountApiConnection[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    autocountService
      .listApiConnections()
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

/** The four designed preview states, mirroring `SqlPreviewState` for the
 * open REST API (AC-08-14/20). `loading` rides the preview-job progress
 * (sprint-5/11, AC-11-27) - `stage`/`pagesDone`/`pagesTotal` are absent
 * until known, never guessed; `cancelling` is set once `cancel()` has been
 * called but the job has not yet reported the terminal state. */
export type HttpPreviewState =
  | { status: 'idle' }
  | {
      status: 'loading';
      stage?: string | null;
      pagesDone?: number | null;
      pagesTotal?: number | null;
      cancelling?: boolean;
    }
  | { status: 'error'; message: string }
  | { status: 'success'; preview: HttpPreview };

/** `useHttpPreview().run`'s optional trailing options - sprint-5/08 review
 * round 1 (B3). Passing both `companyId` + `entityType` makes a clean
 * preview ALSO stamp `resultColumns`/`lastPreviewAt` on the task
 * (AC-08-14), exactly like `previewSqlQuery`'s task-preview counterpart -
 * omitted only for a caller previewing OUTSIDE a task context (none today,
 * kept optional for that reason). */
export interface HttpPreviewRunOptions {
  companyId?: string;
  entityType?: string;
  /** Operator-authored cross-endpoint joins (sprint-5/10, AC-10-05) applied
   * over the sampled page, in order. */
  lookups?: AutocountLookupSpec[];
  /** The task's own combine step (sprint-5/10 S5a follow-up, AC-10-82) -
   * sent ONLY when the caller has one; the response's `rows`/`columns`
   * become the COMBINED shape and the funnel fields populate. */
  combine?: AutocountCombineConfig | null;
}

export interface UseHttpPreviewResult {
  state: HttpPreviewState;
  /**
   * Run the endpoint path (page 1, <=50 rows). Never throws - errors land
   * in state, the field they belong to read via `readFieldErrors`. Resolves
   * the landed `HttpPreview` only when THIS call's own preview is the one
   * that landed (AC-08-20 - the Source tab's save gate needs to know a
   * specific connectionId/path pair was proved, never just "some preview
   * succeeded at some point"; the caller also reads `preview.task` off it,
   * sprint-5/08 review round 7, to `apply()` the freshly-stamped task with
   * no second fetch); a superseded/failed run resolves `false`.
   */
  run: (
    connectionId: string,
    path: string,
    distinctOf?: string[],
    options?: HttpPreviewRunOptions,
  ) => Promise<HttpPreview | false>;
  /** The 422's field (`connectionId` | `path`), when the last run failed on
   * a specific field rather than a generic error. */
  fieldErrors: Record<string, string>;
  reset: () => void;
  /** Cooperative cancel of an in-flight job (AC-11-24) - a no-op while idle
   * or already terminal. */
  cancel: () => void;
}

/**
 * sprint-5/11 (AC-11-20..27) - Test starts the `sample`-scope
 * `autocount_source_preview` job instead of awaiting `preview_http`
 * directly, and polls `GET /autocount/previews/{jobId}` (AC-11-22) against
 * the real backend (S4). `initialJobId` (AC-11-23/27) re-attaches to an
 * already-in-flight job after a remount/reload (`task.previewJobId`) -
 * polled without a fresh `startPreviewJob` call.
 */
export function useHttpPreview(initialJobId?: string | null): UseHttpPreviewResult {
  const [state, setState] = useState<HttpPreviewState>({ status: 'idle' });
  const [fieldErrors, setFieldErrors] = useState<Record<string, string>>({});
  const runId = useRef(0);
  const activeJobId = useRef<string | null>(null);
  const cancelRequested = useRef(false);
  const attachedJobIdRef = useRef<string | null>(null);

  const pollUntilTerminal = useCallback(
    async (jobId: string, id: number): Promise<HttpPreview | false> => {
      for (;;) {
        const job = await autocountService.getPreviewJob(jobId);
        if (id !== runId.current) return false;
        // AC-11-23 - the claim is ONE per task regardless of scope (a
        // `sample` Test job re-attach lands here too, via the SAME
        // `task.previewJobId`): a job that turns out to belong to the
        // OTHER scope was never THIS hook's own run - leave it idle,
        // never a fabricated error/success.
        if (job.scope !== 'sample') {
          setState({ status: 'idle' });
          return false;
        }
        if (job.status === 'queued' || job.status === 'running') {
          setState({
            status: 'loading',
            stage: job.progress?.stage ?? null,
            pagesDone: job.progress?.pagesDone ?? null,
            pagesTotal: job.progress?.pagesTotal ?? null,
            cancelling: cancelRequested.current,
          });
          await pause(PREVIEW_JOB_POLL_MS);
          continue;
        }
        if (job.status === 'cancelled') {
          setState({ status: 'idle' });
          return false;
        }
        if (job.status === 'failed') {
          setFieldErrors(job.fieldErrors ?? {});
          setState({ status: 'error', message: job.error ?? 'The preview could not be run.' });
          return false;
        }
        // done
        if (job.result?.scope === 'sample') {
          setState({ status: 'success', preview: job.result.preview });
          return job.result.preview;
        }
        setState({ status: 'error', message: 'The preview could not be run.' });
        return false;
      }
    },
    [],
  );

  const run = useCallback(
    async (
      connectionId: string,
      path: string,
      distinctOf?: string[],
      options?: HttpPreviewRunOptions,
    ): Promise<HttpPreview | false> => {
      const id = ++runId.current;
      cancelRequested.current = false;
      activeJobId.current = null;
      setState({ status: 'loading' });
      setFieldErrors({});
      try {
        const started = await autocountService.startPreviewJob({
          scope: 'sample',
          companyId: options?.companyId ?? '',
          entityType: options?.entityType ?? '',
          connectionId,
          path,
          distinctOf,
          lookups: options?.lookups,
          combine: options?.combine,
        });
        if (id !== runId.current) return false;
        activeJobId.current = started.jobId;
        attachedJobIdRef.current = started.jobId;
        return await pollUntilTerminal(started.jobId, id);
      } catch (e) {
        if (id !== runId.current) return false;
        const errors = e instanceof ApiError ? readFieldErrors(e.detail) : {};
        setFieldErrors(errors);
        setState({
          status: 'error',
          message: e instanceof ApiError ? e.message : 'The preview could not be run.',
        });
        return false;
      }
    },
    [pollUntilTerminal],
  );

  // AC-11-23/27 - re-attach to an already-in-flight job after a remount/
  // reload (`task.previewJobId`): a poll, never a fresh `startPreviewJob`
  // (which would start a SECOND walk the claim would just reject anyway).
  // Attaches once per job id - a re-render carrying the SAME id (the task
  // re-fetched while this hook is already polling it) is a no-op.
  useEffect(() => {
    if (!initialJobId || attachedJobIdRef.current === initialJobId) return;
    attachedJobIdRef.current = initialJobId;
    const id = ++runId.current;
    cancelRequested.current = false;
    activeJobId.current = initialJobId;
    setState({ status: 'loading' });
    setFieldErrors({});
    void pollUntilTerminal(initialJobId, id);
  }, [initialJobId, pollUntilTerminal]);

  const cancel = useCallback(() => {
    if (!activeJobId.current) return;
    cancelRequested.current = true;
    void autocountService.cancelPreviewJob(activeJobId.current);
  }, []);

  const reset = useCallback(() => {
    runId.current += 1;
    cancelRequested.current = false;
    activeJobId.current = null;
    setState({ status: 'idle' });
    setFieldErrors({});
  }, []);

  return { state, run, fieldErrors, reset, cancel };
}
