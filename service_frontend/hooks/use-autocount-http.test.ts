import { act, renderHook, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { ApiError } from '@/lib/api-client';
import type { AutocountPreviewJob } from '@/types/autocount';

const listApiConnections = vi.fn();
const startPreviewJob = vi.fn();
const getPreviewJob = vi.fn();
const cancelPreviewJob = vi.fn();
vi.mock('@/services/autocount-service', () => ({
  autocountService: {
    listApiConnections: (...a: unknown[]) => listApiConnections(...a),
    startPreviewJob: (...a: unknown[]) => startPreviewJob(...a),
    getPreviewJob: (...a: unknown[]) => getPreviewJob(...a),
    cancelPreviewJob: (...a: unknown[]) => cancelPreviewJob(...a),
  },
}));

const { useAutocountApiConnections, useHttpPreview } = await import('./use-autocount-etl');

function job(over: Partial<AutocountPreviewJob> = {}): AutocountPreviewJob {
  return {
    id: 'preview-job-1',
    scope: 'sample',
    status: 'running',
    progress: null,
    result: null,
    error: null,
    taskError: null,
    createdAt: null,
    ...over,
  };
}

beforeEach(() => {
  listApiConnections.mockReset();
  startPreviewJob.mockReset();
  getPreviewJob.mockReset();
  cancelPreviewJob.mockReset();
});

describe('useAutocountApiConnections (AC-08-15)', () => {
  it('loads and exposes every autocount connection', async () => {
    listApiConnections.mockResolvedValue([
      { id: 'conn-1', name: 'Sorento REST', baseUrl: 'https://hapi.sorento.cc.cd/api/db1', auth: 'none' },
    ]);
    const hook = renderHook(() => useAutocountApiConnections());
    await waitFor(() => expect(hook.result.current.isLoading).toBe(false));
    expect(hook.result.current.connections).toHaveLength(1);
    expect(hook.result.current.error).toBeNull();
  });

  it('degrades to an error message rather than throwing', async () => {
    listApiConnections.mockRejectedValue(new ApiError('Upstream unavailable.', 502));
    const hook = renderHook(() => useAutocountApiConnections());
    await waitFor(() => expect(hook.result.current.isLoading).toBe(false));
    expect(hook.result.current.connections).toEqual([]);
    expect(hook.result.current.error).toBe('Upstream unavailable.');
  });
});

// sprint-5/11 (AC-11-20..27) - Test now starts an `autocount_source_preview`
// job (`sample` scope) and polls it, instead of awaiting `previewHttp`
// directly (the Cloudflare-safe rule). `startPreviewJob`/`getPreviewJob`
// replace `previewHttp` as this hook's OWN calls; the synchronous route
// itself is untouched (proven by `autocount-service.mock.ts`'s job engine).
describe('useHttpPreview (AC-08-14/20, AC-11-20..27)', () => {
  it('queued -> running (with a stage) -> success', async () => {
    startPreviewJob.mockResolvedValue({ jobId: 'preview-job-1', status: 'queued' });
    let resolveRunning!: (v: AutocountPreviewJob) => void;
    getPreviewJob.mockReturnValueOnce(new Promise((r) => (resolveRunning = r)));
    const hook = renderHook(() => useHttpPreview());
    expect(hook.result.current.state.status).toBe('idle');

    let runPromise!: Promise<unknown>;
    act(() => {
      runPromise = hook.result.current.run('conn-1', '/itembypage');
    });
    expect(hook.result.current.state.status).toBe('loading');

    const preview = {
      envelope: 'paged' as const,
      totalCount: 100,
      columns: [{ name: 'ItemCode', sample: 'A1' }],
      rows: [{ ItemCode: 'A1' }],
      durationMs: 50,
    };
    getPreviewJob.mockResolvedValue(
      job({ status: 'done', result: { scope: 'sample', preview } }),
    );
    await act(async () => {
      resolveRunning(job({ status: 'running', progress: { stage: 'source', pagesDone: 0, pagesTotal: 1 } }));
      await runPromise;
    });
    expect(hook.result.current.state).toEqual({ status: 'success', preview });
  });

  it('exposes the stage and page count while running, and never fabricates one', async () => {
    startPreviewJob.mockResolvedValue({ jobId: 'preview-job-2', status: 'queued' });
    getPreviewJob.mockResolvedValue(
      job({ id: 'preview-job-2', status: 'running', progress: { stage: 'lookup:brand', pagesDone: 1, pagesTotal: 2 } }),
    );
    const hook = renderHook(() => useHttpPreview());
    act(() => {
      void hook.result.current.run('conn-1', '/itembypage');
    });
    await waitFor(() =>
      expect(hook.result.current.state).toMatchObject({
        status: 'loading',
        stage: 'lookup:brand',
        pagesDone: 1,
        pagesTotal: 2,
      }),
    );
  });

  it('forwards companyId/entityType to the job start when given (B3, AC-08-14 stamps the task only when both are present)', async () => {
    startPreviewJob.mockResolvedValue({ jobId: 'preview-job-3', status: 'queued' });
    getPreviewJob.mockResolvedValue(
      job({
        id: 'preview-job-3',
        status: 'done',
        result: { scope: 'sample', preview: { envelope: 'list', columns: [], rows: [], durationMs: 1 } },
      }),
    );
    const hook = renderHook(() => useHttpPreview());
    await act(() =>
      hook.result.current.run('conn-1', '/itembypage', undefined, {
        companyId: 'company-1',
        entityType: 'product',
      }),
    );
    expect(startPreviewJob).toHaveBeenCalledWith({
      scope: 'sample',
      connectionId: 'conn-1',
      path: '/itembypage',
      distinctOf: undefined,
      companyId: 'company-1',
      entityType: 'product',
      lookups: undefined,
      combine: undefined,
    });
  });

  it('sends an empty companyId/entityType when no options are given (never today, kept tolerant)', async () => {
    startPreviewJob.mockResolvedValue({ jobId: 'preview-job-4', status: 'queued' });
    getPreviewJob.mockResolvedValue(
      job({
        id: 'preview-job-4',
        status: 'done',
        result: { scope: 'sample', preview: { envelope: 'list', columns: [], rows: [], durationMs: 1 } },
      }),
    );
    const hook = renderHook(() => useHttpPreview());
    await act(() => hook.result.current.run('conn-1', '/itembypage'));
    expect(startPreviewJob).toHaveBeenCalledWith({
      scope: 'sample',
      connectionId: 'conn-1',
      path: '/itembypage',
      distinctOf: undefined,
      companyId: '',
      entityType: '',
      lookups: undefined,
      combine: undefined,
    });
  });

  it('a failed job lands the message AND the per-field error (AC-11-25)', async () => {
    startPreviewJob.mockResolvedValue({ jobId: 'preview-job-5', status: 'queued' });
    getPreviewJob.mockResolvedValue(
      job({
        id: 'preview-job-5',
        status: 'failed',
        error: "'/bogus' was not found.",
        fieldErrors: { path: "'/bogus' was not found." },
      }),
    );
    const hook = renderHook(() => useHttpPreview());
    await act(() => hook.result.current.run('conn-1', '/bogus'));
    expect(hook.result.current.state).toEqual({
      status: 'error',
      message: "'/bogus' was not found.",
    });
    expect(hook.result.current.fieldErrors).toEqual({ path: "'/bogus' was not found." });
  });

  it('a rejected start lands a generic error, never guesses a field', async () => {
    startPreviewJob.mockRejectedValue(new ApiError('bad', 422, null, { fieldErrors: { path: 'bad' } }));
    const hook = renderHook(() => useHttpPreview());
    await act(() => hook.result.current.run('conn-1', '/bogus'));
    expect(hook.result.current.state).toEqual({ status: 'error', message: 'bad' });
    expect(hook.result.current.fieldErrors).toEqual({ path: 'bad' });
  });

  it('reset returns to idle and clears field errors', async () => {
    startPreviewJob.mockRejectedValue(new ApiError('bad', 422, null, { fieldErrors: { path: 'bad' } }));
    const hook = renderHook(() => useHttpPreview());
    await act(() => hook.result.current.run('conn-1', '/bogus'));
    act(() => hook.result.current.reset());
    expect(hook.result.current.state).toEqual({ status: 'idle' });
    expect(hook.result.current.fieldErrors).toEqual({});
  });

  it('cooperative cancel: a cancelled job resolves false and reverts to idle', async () => {
    startPreviewJob.mockResolvedValue({ jobId: 'preview-job-6', status: 'queued' });
    let resolveRunning!: (v: AutocountPreviewJob) => void;
    getPreviewJob.mockReturnValueOnce(new Promise((r) => (resolveRunning = r)));
    cancelPreviewJob.mockResolvedValue(job({ id: 'preview-job-6', status: 'running' }));
    const hook = renderHook(() => useHttpPreview());

    let runPromise!: Promise<unknown>;
    act(() => {
      runPromise = hook.result.current.run('conn-1', '/itembypage');
    });
    await waitFor(() => expect(startPreviewJob).toHaveBeenCalled());

    act(() => hook.result.current.cancel());
    expect(cancelPreviewJob).toHaveBeenCalledWith('preview-job-6');

    getPreviewJob.mockResolvedValue(job({ id: 'preview-job-6', status: 'cancelled' }));
    await act(async () => {
      resolveRunning(job({ id: 'preview-job-6', status: 'running', progress: { stage: 'source', pagesDone: 0, pagesTotal: 1 } }));
      const result = await runPromise;
      expect(result).toBe(false);
    });
    expect(hook.result.current.state).toEqual({ status: 'idle' });
  });

  it('cancel against an idle hook is a no-op', () => {
    const hook = renderHook(() => useHttpPreview());
    act(() => hook.result.current.cancel());
    expect(cancelPreviewJob).not.toHaveBeenCalled();
  });

  it('only the latest run may settle state', async () => {
    // Keyed by jobId rather than call order, so the two runs' promises can
    // never race each other's mock queue.
    const pendingGets = new Map<string, { resolve: (v: AutocountPreviewJob) => void }>();
    getPreviewJob.mockImplementation(
      (jobId: string) =>
        new Promise<AutocountPreviewJob>((resolve) => {
          pendingGets.set(jobId, { resolve });
        }),
    );
    startPreviewJob.mockImplementation((input: { path: string }) =>
      Promise.resolve({
        jobId: input.path === '/itembypage' ? 'preview-job-7' : 'preview-job-8',
        status: 'queued' as const,
      }),
    );

    const hook = renderHook(() => useHttpPreview());
    let first!: Promise<unknown>;
    await act(async () => {
      first = hook.result.current.run('conn-1', '/itembypage');
      await waitFor(() => expect(pendingGets.has('preview-job-7')).toBe(true));
    });

    let second!: Promise<unknown>;
    await act(async () => {
      second = hook.result.current.run('conn-1', '/ItemGroup');
      await waitFor(() => expect(pendingGets.has('preview-job-8')).toBe(true));
    });

    await act(async () => {
      pendingGets
        .get('preview-job-8')!
        .resolve(
          job({
            id: 'preview-job-8',
            status: 'done',
            result: { scope: 'sample', preview: { envelope: 'list', columns: [], rows: [], durationMs: 10 } },
          }),
        );
      await second;
    });
    expect(hook.result.current.state.status).toBe('success');

    await act(async () => {
      pendingGets
        .get('preview-job-7')!
        .resolve(job({ id: 'preview-job-7', status: 'running', progress: { stage: 'source', pagesDone: 0, pagesTotal: 1 } }));
      await first;
    });
    // The stale first run must not overwrite the newer success.
    expect(hook.result.current.state).toMatchObject({ status: 'success' });
    if (hook.result.current.state.status === 'success') {
      expect(hook.result.current.state.preview.envelope).toBe('list');
    }
  });
});
