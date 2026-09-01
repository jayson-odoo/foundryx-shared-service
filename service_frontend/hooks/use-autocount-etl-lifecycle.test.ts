import { act, renderHook, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { ApiError } from '@/lib/api-client';
import type { AutocountEtlTask } from '@/types/autocount';

const previewEtlTask = vi.fn();
const activateEtlTask = vi.fn();
const pauseEtlTask = vi.fn();
const resumeEtlTask = vi.fn();
const runEtlTaskNow = vi.fn();
vi.mock('@/services/autocount-service', () => ({
  autocountService: {
    previewEtlTask: (...a: unknown[]) => previewEtlTask(...a),
    activateEtlTask: (...a: unknown[]) => activateEtlTask(...a),
    pauseEtlTask: (...a: unknown[]) => pauseEtlTask(...a),
    resumeEtlTask: (...a: unknown[]) => resumeEtlTask(...a),
    runEtlTaskNow: (...a: unknown[]) => runEtlTaskNow(...a),
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
      lineKeyColumn: null,
      lineProductColumn: null,
      lineWarehouseColumn: null,
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
  for (const fn of [previewEtlTask, activateEtlTask, pauseEtlTask, resumeEtlTask, runEtlTaskNow]) {
    fn.mockReset();
  }
});

describe('useEtlTaskPreview (AC-22-18)', () => {
  it('lands a completed dry run in success and hands the stamped task up', async () => {
    const stamped = task({ lastPreviewAt: '2026-08-30T06:21:00Z' });
    previewEtlTask.mockResolvedValue({
      task: stamped,
      preview: { previewable: true, sink: 'sorento', summary: { total: 1, created: 1, updated: 0, failed: 0, retryable: 0 }, predictions: [] },
    });
    const onTask = vi.fn();
    const { result } = renderHook(() => useEtlTaskPreview('c1', 'customer', onTask));
    expect(result.current.state.status).toBe('idle');
    await act(() => result.current.run());
    expect(result.current.state.status).toBe('success');
    expect(onTask).toHaveBeenCalledWith(stamped);
  });

  it('renders a Sorento anchor 422 as a TASK error with its code, not a dry-run failure', async () => {
    previewEtlTask.mockRejectedValue(
      new ApiError('No company.', 422, null, { code: 'UNKNOWN_COMPANY', message: 'No company "ZZ".' }),
    );
    const { result } = renderHook(() => useEtlTaskPreview('c1', 'customer', vi.fn()));
    await act(() => result.current.run());
    expect(result.current.state).toEqual({
      status: 'taskError',
      error: { code: 'UNKNOWN_COMPANY', message: 'No company "ZZ".' },
    });
  });

  it('keeps a 502 as the dry-run error state', async () => {
    previewEtlTask.mockRejectedValue(new ApiError('Consumer unreachable.', 502));
    const { result } = renderHook(() => useEtlTaskPreview('c1', 'customer', vi.fn()));
    await act(() => result.current.run());
    expect(result.current.state).toEqual({ status: 'error', message: 'Consumer unreachable.' });
    act(() => result.current.reset());
    expect(result.current.state.status).toBe('idle');
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
});
