import { act, renderHook, waitFor } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { ApiError } from '@/lib/api-client';

const setDeliveryMode = vi.fn();
const previewColumns = vi.fn();
const issuePullKey = vi.fn();
const buildPullSnapshot = vi.fn();
const getPullSnapshot = vi.fn();
const getPullSnapshotRows = vi.fn();

vi.mock('@/services/autocount-service', () => ({
  autocountService: {
    setDeliveryMode: (...a: unknown[]) => setDeliveryMode(...a),
    previewColumns: (...a: unknown[]) => previewColumns(...a),
    issuePullKey: (...a: unknown[]) => issuePullKey(...a),
    buildPullSnapshot: (...a: unknown[]) => buildPullSnapshot(...a),
    getPullSnapshot: (...a: unknown[]) => getPullSnapshot(...a),
    getPullSnapshotRows: (...a: unknown[]) => getPullSnapshotRows(...a),
  },
}));

const {
  useSetDeliveryMode,
  usePreviewColumnsMap,
  useIssuePullKey,
  useBuildPullSnapshot,
  usePullSnapshotDetail,
  usePullSnapshotRows,
} = await import('./use-autocount-pull');

describe('useSetDeliveryMode (AC-10-11/16)', () => {
  it('saves and returns the updated entity config', async () => {
    setDeliveryMode.mockResolvedValueOnce({ id: 'e1', entityType: 'product', deliveryMode: 'pull' });
    const { result } = renderHook(() => useSetDeliveryMode());
    let saved;
    await act(async () => {
      saved = await result.current.save('c1', 'product', 'pull');
    });
    expect(setDeliveryMode).toHaveBeenCalledWith('c1', 'product', 'pull');
    expect(saved).toMatchObject({ ok: true, config: { deliveryMode: 'pull' } });
    expect(result.current.error).toBeNull();
  });

  it('surfaces a 422 field error on the RESOLVED value (never only hook state - sprint-5/13 fix, a caller reading it after an await sees a stale closure)', async () => {
    setDeliveryMode.mockRejectedValueOnce(
      new ApiError('The task could not be saved. Fix the highlighted fields.', 422, null, {
        fieldErrors: { deliveryMode: 'Set a Sorento company code before enabling pull.' },
      }),
    );
    const { result } = renderHook(() => useSetDeliveryMode());
    let saved;
    await act(async () => {
      saved = await result.current.save('c1', 'product', 'pull');
    });
    expect(saved).toMatchObject({
      ok: false,
      message: 'The task could not be saved. Fix the highlighted fields.',
      fieldErrors: { deliveryMode: 'Set a Sorento company code before enabling pull.' },
    });
    // Hook state is ALSO populated (for a render-time inline consumer) -
    // just never what a post-await closure should rely on.
    expect(result.current.fieldErrors.deliveryMode).toMatch(/Sorento company code/);
    expect(result.current.error).toBe('The task could not be saved. Fix the highlighted fields.');
  });

  it('a non-ApiError rejection falls back to a generic message with no field errors', async () => {
    setDeliveryMode.mockRejectedValueOnce(new Error('network blip'));
    const { result } = renderHook(() => useSetDeliveryMode());
    let saved;
    await act(async () => {
      saved = await result.current.save('c1', 'product', 'pull');
    });
    expect(saved).toMatchObject({ ok: false, message: 'The delivery mode could not be saved.', fieldErrors: {} });
  });
});

describe('usePreviewColumnsMap (AC-10-05 companion probe)', () => {
  it('tracks columns per key independently - one row Test never clobbers another', async () => {
    previewColumns.mockResolvedValueOnce(['ItemCode', 'UOM', 'Rate', 'Price']);
    const { result } = renderHook(() => usePreviewColumnsMap());
    await act(async () => {
      await result.current.run('row-0', 'conn-1', '/itemuombypage');
    });
    expect(result.current.columnsByKey['row-0']).toEqual(['ItemCode', 'UOM', 'Rate', 'Price']);
    expect(result.current.columnsByKey['row-1']).toBeUndefined();
  });

  it('a probe failure is scoped to its own key', async () => {
    previewColumns.mockRejectedValueOnce(new ApiError('Not found.', 404));
    const { result } = renderHook(() => usePreviewColumnsMap());
    await act(async () => {
      await result.current.run('row-0', 'conn-1', '/bad');
    });
    expect(result.current.errorsByKey['row-0']).toBe('Not found.');
    expect(result.current.columnsByKey['row-0']).toBeUndefined();
  });
});

describe('useIssuePullKey (AC-10-28)', () => {
  it('resolves the plaintext exactly once', async () => {
    issuePullKey.mockResolvedValueOnce({
      key: { id: 'k1', name: 'Prod', companyIds: ['c1'], keyPrefix: 'fxa_live_ab', createdAt: null, lastUsedAt: null, revokedAt: null },
      plaintext: 'fxa_live_abcdef',
    });
    const { result } = renderHook(() => useIssuePullKey());
    let issued;
    await act(async () => {
      issued = await result.current.issue({ name: 'Prod', companyIds: ['c1'] });
    });
    expect(issued).toMatchObject({ plaintext: 'fxa_live_abcdef' });
  });
});

describe('useBuildPullSnapshot (AC-10-26/37)', () => {
  it('builds and surfaces a service error', async () => {
    buildPullSnapshot.mockRejectedValueOnce(new ApiError('Within the 60s build cooldown.', 429));
    const { result } = renderHook(() => useBuildPullSnapshot());
    let snapshot;
    await act(async () => {
      snapshot = await result.current.build('c1', 'product');
    });
    expect(snapshot).toBeNull();
    expect(result.current.error).toMatch(/cooldown/);
  });
});

describe('usePullSnapshotDetail (AC-10-49) - polls while building', () => {
  it('a ready snapshot resolves and the hook reads its status', async () => {
    getPullSnapshot.mockResolvedValueOnce({ id: 's1', status: 'ready', entityType: 'product', recordCount: 10 });
    const { result } = renderHook(() => usePullSnapshotDetail('s1'));
    await waitFor(() => expect(result.current.state.status).toBe('ready'));
    expect(getPullSnapshot).toHaveBeenCalledTimes(1);
  });

  it('schedules a re-poll while the snapshot is still building (never while ready/failed)', async () => {
    getPullSnapshot.mockResolvedValue({ id: 's1', status: 'building', entityType: 'product' });
    const setTimeoutSpy = vi.spyOn(globalThis, 'setTimeout');
    renderHook(() => usePullSnapshotDetail('s1'));
    await waitFor(() =>
      expect(setTimeoutSpy.mock.calls.some((call) => call[1] === 3000)).toBe(true),
    );
    setTimeoutSpy.mockRestore();
  });

  it('a 404 reads as notFound, never a generic error', async () => {
    getPullSnapshot.mockRejectedValueOnce(new ApiError('Not found.', 404));
    const { result } = renderHook(() => usePullSnapshotDetail('missing'));
    await waitFor(() => expect(result.current.state.status).toBe('notFound'));
  });
});

describe('usePullSnapshotRows (AC-10-49)', () => {
  it('loads a page', async () => {
    getPullSnapshotRows.mockResolvedValueOnce({
      snapshotId: 's1',
      page: 1,
      pageSize: 1000,
      totalPages: 1,
      recordCount: 1,
      rows: [{ code: 'A' }],
    });
    const { result } = renderHook(() => usePullSnapshotRows('s1'));
    await act(async () => {
      await result.current.run(0, 1000);
    });
    expect(result.current.state.status).toBe('success');
    expect(getPullSnapshotRows).toHaveBeenCalledWith('s1', 0, 1000);
  });
});
