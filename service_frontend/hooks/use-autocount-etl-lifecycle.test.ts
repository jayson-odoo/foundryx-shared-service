import { act, renderHook, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { ApiError } from '@/lib/api-client';
import type { AutocountEtlTask, AutocountPreviewJob } from '@/types/autocount';

const activateEtlTask = vi.fn();
const pauseEtlTask = vi.fn();
const resumeEtlTask = vi.fn();
const runEtlTaskNow = vi.fn();
const startPreviewJob = vi.fn();
const getPreviewJob = vi.fn();
const cancelPreviewJob = vi.fn();
vi.mock('@/services/autocount-service', () => ({
  autocountService: {
    activateEtlTask: (...a: unknown[]) => activateEtlTask(...a),
    pauseEtlTask: (...a: unknown[]) => pauseEtlTask(...a),
    resumeEtlTask: (...a: unknown[]) => resumeEtlTask(...a),
    runEtlTaskNow: (...a: unknown[]) => runEtlTaskNow(...a),
    startPreviewJob: (...a: unknown[]) => startPreviewJob(...a),
    getPreviewJob: (...a: unknown[]) => getPreviewJob(...a),
    cancelPreviewJob: (...a: unknown[]) => cancelPreviewJob(...a),
  },
}));

const { useEtlTaskLifecycle, useEtlTaskPreview } = await import('./use-autocount-etl');

function task(over: Partial<AutocountEtlTask> = {}): AutocountEtlTask {
  return {
    companyId: 'c1',
    entityType: 'customer',
    etlStatus: 'draft',
    activatedAt: null,
    sourceConfig: {
      connectionId: 'conn-sql-1',
      query: 'SELECT 1',
      lineQuery: null,
      keyColumns: ['AccNo'],
      watermarkColumn: null,
      comparedColumns: [],
      fromDate: null,
      docDateColumn: null,
      filterFormula: null,
      incrementalMinutes: 5,
      reconcileMode: 'dailyAt',
      reconcileHours: null,
      reconcileAt: '02:00',
    },
    resultColumns: ['AccNo'],
    lastPreviewAt: null,
    lastPreviewFailedCount: null,
    lastRunAt: null,
    lastRunError: null,
    lastRunErrorCode: null,
    nextIncrementalAt: null,
    nextReconcileAt: null,
    ...over,
  };
}

beforeEach(() => {
  for (const fn of [
    activateEtlTask,
    pauseEtlTask,
    resumeEtlTask,
    runEtlTaskNow,
    startPreviewJob,
    getPreviewJob,
    cancelPreviewJob,
  ]) {
    fn.mockReset();
  }
});

function previewJob(over: Partial<AutocountPreviewJob> = {}): AutocountPreviewJob {
  return {
    id: 'preview-job-1',
    scope: 'full',
    status: 'running',
    progress: null,
    result: null,
    error: null,
    taskError: null,
    createdAt: null,
    ...over,
  };
}

// sprint-5/11 (AC-11-20..27) - "Run preview" now starts an
// `autocount_source_preview` job (`full` scope) and polls it, instead of
// awaiting `preview_task` directly (the Cloudflare-safe rule).
// `startPreviewJob`/`getPreviewJob` replace `previewEtlTask` as this hook's
// OWN calls; the synchronous route itself is untouched (proven by
// `autocount-service.mock.ts`'s job engine).
describe('useEtlTaskPreview (AC-22-18, AC-11-20..27)', () => {
  it('lands a completed dry run in success and hands the stamped task up', async () => {
    const stamped = task({ lastPreviewAt: '2026-08-30T06:21:00Z' });
    startPreviewJob.mockResolvedValue({ jobId: 'preview-job-1', status: 'queued' });
    getPreviewJob.mockResolvedValue(
      previewJob({
        status: 'done',
        result: {
          scope: 'full',
          task: stamped,
          preview: {
            previewable: true,
            sink: 'sorento',
            summary: { total: 1, created: 1, updated: 0, failed: 0, retryable: 0 },
            predictions: [],
          },
        },
      }),
    );
    const onTask = vi.fn();
    const { result } = renderHook(() => useEtlTaskPreview('c1', 'customer', onTask));
    expect(result.current.state.status).toBe('idle');
    await act(() => result.current.run());
    expect(startPreviewJob).toHaveBeenCalledWith({ scope: 'full', companyId: 'c1', entityType: 'customer' });
    expect(result.current.state.status).toBe('success');
    expect(onTask).toHaveBeenCalledWith(stamped);
  });

  it('exposes the stage and page count while running', async () => {
    startPreviewJob.mockResolvedValue({ jobId: 'preview-job-2', status: 'queued' });
    getPreviewJob.mockResolvedValue(
      previewJob({ id: 'preview-job-2', status: 'running', progress: { stage: 'mapping', pagesDone: 5, pagesTotal: 12 } }),
    );
    const { result } = renderHook(() => useEtlTaskPreview('c1', 'customer', vi.fn()));
    act(() => {
      void result.current.run();
    });
    await waitFor(() =>
      expect(result.current.state).toMatchObject({
        status: 'loading',
        stage: 'mapping',
        pagesDone: 5,
        pagesTotal: 12,
      }),
    );
  });

  it('renders a Sorento anchor 422 as a TASK error with its code, not a dry-run failure', async () => {
    startPreviewJob.mockResolvedValue({ jobId: 'preview-job-3', status: 'queued' });
    getPreviewJob.mockResolvedValue(
      previewJob({
        id: 'preview-job-3',
        status: 'failed',
        taskError: { code: 'UNKNOWN_COMPANY', message: 'No company "ZZ".' },
        error: 'No company "ZZ".',
      }),
    );
    const { result } = renderHook(() => useEtlTaskPreview('c1', 'customer', vi.fn()));
    await act(() => result.current.run());
    expect(result.current.state).toEqual({
      status: 'taskError',
      error: { code: 'UNKNOWN_COMPANY', message: 'No company "ZZ".' },
    });
  });

  it('keeps a consumer failure as the dry-run error state', async () => {
    startPreviewJob.mockResolvedValue({ jobId: 'preview-job-4', status: 'queued' });
    getPreviewJob.mockResolvedValue(
      previewJob({ id: 'preview-job-4', status: 'failed', error: 'Consumer unreachable.' }),
    );
    const { result } = renderHook(() => useEtlTaskPreview('c1', 'customer', vi.fn()));
    await act(() => result.current.run());
    expect(result.current.state).toEqual({ status: 'error', message: 'Consumer unreachable.' });
    act(() => result.current.reset());
    expect(result.current.state.status).toBe('idle');
  });

  it('a rejected start (409 - unconfigured) lands the generic error state', async () => {
    startPreviewJob.mockRejectedValue(new ApiError('Save a query with key columns before previewing.', 409));
    const { result } = renderHook(() => useEtlTaskPreview('c1', 'customer', vi.fn()));
    await act(() => result.current.run());
    expect(result.current.state).toEqual({
      status: 'error',
      message: 'Save a query with key columns before previewing.',
    });
  });

  it('cooperative cancel: a cancelled job reverts to idle, never a stale success', async () => {
    startPreviewJob.mockResolvedValue({ jobId: 'preview-job-5', status: 'queued' });
    let resolveRunning!: (v: AutocountPreviewJob) => void;
    getPreviewJob.mockReturnValueOnce(new Promise((r) => (resolveRunning = r)));
    cancelPreviewJob.mockResolvedValue(previewJob({ id: 'preview-job-5', status: 'running' }));
    const { result } = renderHook(() => useEtlTaskPreview('c1', 'customer', vi.fn()));

    let runPromise!: Promise<void>;
    act(() => {
      runPromise = result.current.run();
    });
    await waitFor(() => expect(startPreviewJob).toHaveBeenCalled());

    act(() => result.current.cancel());
    expect(cancelPreviewJob).toHaveBeenCalledWith('preview-job-5');

    getPreviewJob.mockResolvedValue(previewJob({ id: 'preview-job-5', status: 'cancelled' }));
    await act(async () => {
      resolveRunning(previewJob({ id: 'preview-job-5', status: 'running' }));
      await runPromise;
    });
    expect(result.current.state).toEqual({ status: 'idle' });
  });
});

describe('useEtlTaskLifecycle (AC-22-18/19)', () => {
  it('activates, pauses and resumes, adopting each returned task', async () => {
    activateEtlTask.mockResolvedValue(task({ etlStatus: 'active' }));
    pauseEtlTask.mockResolvedValue(task({ etlStatus: 'paused' }));
    resumeEtlTask.mockResolvedValue(task({ etlStatus: 'active' }));
    const onTask = vi.fn();
    const { result } = renderHook(() => useEtlTaskLifecycle('c1', 'customer', onTask));

    await act(async () => {
      expect(await result.current.activate()).toBe(true);
    });
    await act(async () => {
      expect(await result.current.pause()).toBe(true);
    });
    await act(async () => {
      expect(await result.current.resume()).toBe(true);
    });
    expect(onTask.mock.calls.map((c) => c[0].etlStatus)).toEqual(['active', 'paused', 'active']);
    expect(result.current.busy).toBeNull();
    expect(result.current.error).toBeNull();
  });

  it('surfaces the server gate (409) inline and reports false', async () => {
    activateEtlTask.mockRejectedValue(new ApiError('Run a successful preview before activating.', 409));
    const { result } = renderHook(() => useEtlTaskLifecycle('c1', 'customer', vi.fn()));
    await act(async () => {
      expect(await result.current.activate()).toBe(false);
    });
    await waitFor(() =>
      expect(result.current.error).toBe('Run a successful preview before activating.'),
    );
    act(() => result.current.clearError());
    expect(result.current.error).toBeNull();
  });

  it('Run now resolves to the run id and adopts the refreshed task', async () => {
    const refreshed = task({ etlStatus: 'active', lastRunAt: '2026-08-30T07:00:00Z' });
    runEtlTaskNow.mockResolvedValue({ runId: 'run-9', jobId: 'job-9', status: 'done', task: refreshed });
    const onTask = vi.fn();
    const { result } = renderHook(() => useEtlTaskLifecycle('c1', 'customer', onTask));
    let runId: string | null = null;
    await act(async () => {
      runId = await result.current.runNow();
    });
    expect(runId).toBe('run-9');
    expect(onTask).toHaveBeenCalledWith(refreshed);
  });

  // "Re-push all" (plan sprint-5/07) no longer rides this hook - review
  // round: it moved onto the core deferred-actions engine
  // (`useDeferredAction`, `autocount_etl_task.repush`) the same way every
  // other destructive action in the app works (D2/D13). See
  // `activate-tab.tsx`/`activate-tab.test.tsx` for its coverage now.
});
