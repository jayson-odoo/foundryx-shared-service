import { act, renderHook, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { ApiError } from '@/lib/api-client';
import type { AutocountPreviewJob } from '@/types/autocount';

const startPreviewJob = vi.fn();
const getPreviewJob = vi.fn();
const cancelPreviewJob = vi.fn();
vi.mock('@/services/autocount-service', () => ({
  autocountService: {
    startPreviewJob: (...a: unknown[]) => startPreviewJob(...a),
    getPreviewJob: (...a: unknown[]) => getPreviewJob(...a),
    cancelPreviewJob: (...a: unknown[]) => cancelPreviewJob(...a),
  },
}));

const { useAutocountPreviewJob } = await import('./use-autocount-preview-job');

function job(over: Partial<AutocountPreviewJob> = {}): AutocountPreviewJob {
  return {
    id: 'preview-job-1',
    scope: 'sample',
    status: 'queued',
    progress: null,
    result: null,
    error: null,
    taskError: null,
    createdAt: '2026-09-21T00:00:00Z',
    ...over,
  };
}

beforeEach(() => {
  startPreviewJob.mockReset();
  getPreviewJob.mockReset();
  cancelPreviewJob.mockReset();
});

// A fast poll cadence keeps every test well under Vitest's default timeout
// without needing fake timers.
const POLL_MS = 5;

describe('useAutocountPreviewJob (AC-11-20/27)', () => {
  it('idle before start', () => {
    const { result } = renderHook(() => useAutocountPreviewJob(POLL_MS));
    expect(result.current.state.phase).toBe('idle');
    expect(result.current.busy).toBe(false);
  });

  it('queued -> running with a stage and page count -> done (sample)', async () => {
    startPreviewJob.mockResolvedValue({ jobId: 'preview-job-1', status: 'queued' });
    getPreviewJob
      .mockResolvedValueOnce(job({ status: 'running', progress: { stage: 'source', pagesDone: 0, pagesTotal: 1 } }))
      .mockResolvedValueOnce(
        job({
          status: 'done',
          progress: { stage: 'storing', pagesDone: 1, pagesTotal: 1 },
          result: { scope: 'sample', preview: { envelope: 'list', columns: [], rows: [], durationMs: 5 } },
        }),
      );
    const { result } = renderHook(() => useAutocountPreviewJob(POLL_MS));

    await act(async () => {
      await result.current.start({
        scope: 'sample',
        companyId: 'c1',
        entityType: 'product',
        connectionId: 'conn-1',
        path: '/itembypage',
      });
    });
    expect(result.current.busy).toBe(true);

    await waitFor(() => expect(result.current.state.phase).toBe('running'));
    expect(result.current.state.job?.progress).toEqual({ stage: 'source', pagesDone: 0, pagesTotal: 1 });

    await waitFor(() => expect(result.current.state.phase).toBe('done'));
    expect(result.current.busy).toBe(false);
    expect(result.current.state.job?.result).toEqual({
      scope: 'sample',
      preview: { envelope: 'list', columns: [], rows: [], durationMs: 5 },
    });
  });

  it('running with no page count known yet (never guessed)', async () => {
    startPreviewJob.mockResolvedValue({ jobId: 'preview-job-2', status: 'queued' });
    getPreviewJob.mockResolvedValue(job({ id: 'preview-job-2', status: 'running', progress: null }));
    const { result, unmount } = renderHook(() => useAutocountPreviewJob(POLL_MS));

    await act(async () => {
      await result.current.start({ scope: 'full', companyId: 'c1', entityType: 'product' });
    });
    await waitFor(() => expect(result.current.state.phase).toBe('running'));
    expect(result.current.state.job?.progress).toBeNull();
    // This job never terminates in this fixture - stop the poll loop rather
    // than leaking a timer into the next test.
    unmount();
  });

  it('done (full) carries the stamped task echo', async () => {
    startPreviewJob.mockResolvedValue({ jobId: 'preview-job-3', status: 'queued' });
    getPreviewJob.mockResolvedValueOnce(
      job({
        id: 'preview-job-3',
        scope: 'full',
        status: 'done',
        result: {
          scope: 'full',
          task: { companyId: 'c1', entityType: 'product', lastPreviewAt: '2026-09-21T00:05:00Z' } as never,
          preview: { previewable: false, sink: 'logging', reason: 'No consumer configured.' },
        },
      }),
    );
    const { result } = renderHook(() => useAutocountPreviewJob(POLL_MS));
    await act(async () => {
      await result.current.start({ scope: 'full', companyId: 'c1', entityType: 'product' });
    });
    await waitFor(() => expect(result.current.state.phase).toBe('done'));
    expect(result.current.state.job?.result?.scope).toBe('full');
  });

  it('failed carries the operator-safe message', async () => {
    startPreviewJob.mockResolvedValue({ jobId: 'preview-job-4', status: 'queued' });
    getPreviewJob.mockResolvedValueOnce(
      job({ id: 'preview-job-4', status: 'failed', error: 'Source page 2 of 4 failed after retries (timeout).' }),
    );
    const { result } = renderHook(() => useAutocountPreviewJob(POLL_MS));
    await act(async () => {
      await result.current.start({
        scope: 'sample',
        companyId: 'c1',
        entityType: 'product',
        connectionId: 'conn-1',
        path: '/itembypage',
      });
    });
    await waitFor(() => expect(result.current.state.phase).toBe('failed'));
    expect(result.current.state.job?.error).toBe('Source page 2 of 4 failed after retries (timeout).');
    expect(result.current.busy).toBe(false);
  });

  it('a rejected start lands failed with no job id', async () => {
    startPreviewJob.mockRejectedValue(new ApiError('The connection is not yours.', 404));
    const { result } = renderHook(() => useAutocountPreviewJob(POLL_MS));
    await act(async () => {
      await result.current.start({
        scope: 'sample',
        companyId: 'c1',
        entityType: 'product',
        connectionId: 'conn-1',
        path: '/itembypage',
      });
    });
    expect(result.current.state.phase).toBe('failed');
    expect(result.current.state.job?.error).toBe('The connection is not yours.');
    expect(getPreviewJob).not.toHaveBeenCalled();
  });

  it('cancelling -> cancelled', async () => {
    startPreviewJob.mockResolvedValue({ jobId: 'preview-job-5', status: 'queued' });
    getPreviewJob
      .mockResolvedValueOnce(job({ id: 'preview-job-5', status: 'running', progress: { stage: 'source', pagesDone: 0, pagesTotal: 1 } }))
      .mockResolvedValueOnce(job({ id: 'preview-job-5', status: 'running', progress: { stage: 'source', pagesDone: 0, pagesTotal: 1 } }))
      .mockResolvedValueOnce(job({ id: 'preview-job-5', status: 'cancelled' }));
    cancelPreviewJob.mockResolvedValue(job({ id: 'preview-job-5', status: 'running' }));
    const { result } = renderHook(() => useAutocountPreviewJob(POLL_MS));

    await act(async () => {
      await result.current.start({
        scope: 'sample',
        companyId: 'c1',
        entityType: 'product',
        connectionId: 'conn-1',
        path: '/itembypage',
      });
    });
    await waitFor(() => expect(result.current.state.phase).toBe('running'));

    await act(async () => {
      await result.current.cancel();
    });
    expect(result.current.state.phase).toBe('cancelling');
    expect(result.current.busy).toBe(true);
    expect(cancelPreviewJob).toHaveBeenCalledWith('preview-job-5');

    await waitFor(() => expect(result.current.state.phase).toBe('cancelled'));
    expect(result.current.busy).toBe(false);
  });

  it('cancel against an idle hook is a no-op', async () => {
    const { result } = renderHook(() => useAutocountPreviewJob(POLL_MS));
    await act(async () => {
      await result.current.cancel();
    });
    expect(cancelPreviewJob).not.toHaveBeenCalled();
    expect(result.current.state.phase).toBe('idle');
  });

  it('attach re-polls an in-flight job id after a remount (AC-11-23/27)', async () => {
    let resolveFirst!: (v: AutocountPreviewJob) => void;
    getPreviewJob.mockReturnValueOnce(new Promise((r) => (resolveFirst = r)));
    const { result } = renderHook(() => useAutocountPreviewJob(POLL_MS));

    act(() => {
      result.current.attach('preview-job-6');
    });
    expect(startPreviewJob).not.toHaveBeenCalled();
    expect(result.current.state.phase).toBe('queued');

    getPreviewJob.mockResolvedValue(
      job({
        id: 'preview-job-6',
        status: 'done',
        result: { scope: 'sample', preview: { envelope: 'list', columns: [], rows: [], durationMs: 1 } },
      }),
    );
    await act(async () => {
      resolveFirst(
        job({ id: 'preview-job-6', status: 'running', progress: { stage: 'mapping', pagesDone: 3, pagesTotal: 12 } }),
      );
      await Promise.resolve();
    });
    expect(result.current.state.job?.progress).toEqual({ stage: 'mapping', pagesDone: 3, pagesTotal: 12 });
    await waitFor(() => expect(result.current.state.phase).toBe('done'));
  });

  it('reset returns to idle and stops polling', async () => {
    startPreviewJob.mockResolvedValue({ jobId: 'preview-job-7', status: 'queued' });
    getPreviewJob.mockResolvedValue(job({ id: 'preview-job-7', status: 'running', progress: { stage: 'source', pagesDone: 0, pagesTotal: 1 } }));
    const { result } = renderHook(() => useAutocountPreviewJob(POLL_MS));
    await act(async () => {
      await result.current.start({
        scope: 'sample',
        companyId: 'c1',
        entityType: 'product',
        connectionId: 'conn-1',
        path: '/itembypage',
      });
    });
    await waitFor(() => expect(result.current.state.phase).toBe('running'));
    const pollsBeforeReset = getPreviewJob.mock.calls.length;

    act(() => result.current.reset());
    expect(result.current.state).toEqual({ phase: 'idle', job: null });

    await new Promise((r) => setTimeout(r, POLL_MS * 4));
    // No further polls land once reset has invalidated the run token.
    expect(getPreviewJob.mock.calls.length).toBe(pollsBeforeReset);
  });
});
