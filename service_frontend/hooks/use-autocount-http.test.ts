import { act, renderHook, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { ApiError } from '@/lib/api-client';

const listApiConnections = vi.fn();
const previewHttp = vi.fn();
vi.mock('@/services/autocount-service', () => ({
  autocountService: {
    listApiConnections: (...a: unknown[]) => listApiConnections(...a),
    previewHttp: (...a: unknown[]) => previewHttp(...a),
  },
}));

const { useAutocountApiConnections, useHttpPreview } = await import('./use-autocount-etl');

beforeEach(() => {
  listApiConnections.mockReset();
  previewHttp.mockReset();
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

describe('useHttpPreview (AC-08-14/20)', () => {
  it('idle -> loading -> success', async () => {
    let resolve!: (v: unknown) => void;
    previewHttp.mockReturnValue(new Promise((r) => (resolve = r)));
    const hook = renderHook(() => useHttpPreview());
    expect(hook.result.current.state.status).toBe('idle');

    let runPromise!: Promise<void>;
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
    await act(async () => {
      resolve(preview);
      await runPromise;
    });
    expect(hook.result.current.state).toEqual({ status: 'success', preview });
  });

  it('forwards companyId/entityType to the service when given (B3, sprint-5/08 review round 1 - AC-08-14 stamps the task only when both are present)', async () => {
    previewHttp.mockResolvedValue({ envelope: 'list', columns: [], rows: [], durationMs: 1 });
    const hook = renderHook(() => useHttpPreview());
    await act(() =>
      hook.result.current.run('conn-1', '/itembypage', undefined, {
        companyId: 'company-1',
        entityType: 'product',
      }),
    );
    expect(previewHttp).toHaveBeenCalledWith({
      connectionId: 'conn-1',
      path: '/itembypage',
      distinctOf: undefined,
      companyId: 'company-1',
      entityType: 'product',
    });
  });

  it('omits companyId/entityType when no options are given', async () => {
    previewHttp.mockResolvedValue({ envelope: 'list', columns: [], rows: [], durationMs: 1 });
    const hook = renderHook(() => useHttpPreview());
    await act(() => hook.result.current.run('conn-1', '/itembypage'));
    expect(previewHttp).toHaveBeenCalledWith({
      connectionId: 'conn-1',
      path: '/itembypage',
      distinctOf: undefined,
      companyId: undefined,
      entityType: undefined,
    });
  });

  it('a 422 lands the message AND the per-field error', async () => {
    previewHttp.mockRejectedValue(
      new ApiError("'/bogus' was not found.", 422, null, {
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

  it('reset returns to idle and clears field errors', async () => {
    previewHttp.mockRejectedValue(new ApiError('bad', 422, null, { fieldErrors: { path: 'bad' } }));
    const hook = renderHook(() => useHttpPreview());
    await act(() => hook.result.current.run('conn-1', '/bogus'));
    act(() => hook.result.current.reset());
    expect(hook.result.current.state).toEqual({ status: 'idle' });
    expect(hook.result.current.fieldErrors).toEqual({});
  });

  it('only the latest run may settle state', async () => {
    let resolveFirst!: (v: unknown) => void;
    previewHttp.mockReturnValueOnce(new Promise((r) => (resolveFirst = r)));
    const hook = renderHook(() => useHttpPreview());
    let first!: Promise<void>;
    act(() => {
      first = hook.result.current.run('conn-1', '/itembypage');
    });
    previewHttp.mockResolvedValueOnce({
      envelope: 'list',
      columns: [],
      rows: [],
      durationMs: 10,
    });
    await act(() => hook.result.current.run('conn-1', '/ItemGroup'));
    expect(hook.result.current.state.status).toBe('success');
    await act(async () => {
      resolveFirst({ envelope: 'paged', totalCount: 1, columns: [], rows: [], durationMs: 1 });
      await first;
    });
    // The stale first run must not overwrite the newer success.
    expect(hook.result.current.state).toMatchObject({ status: 'success' });
    if (hook.result.current.state.status === 'success') {
      expect(hook.result.current.state.preview.envelope).toBe('list');
    }
  });
});
