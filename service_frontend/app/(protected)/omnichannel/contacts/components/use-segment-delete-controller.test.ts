/**
 * Segment delete controller (plan 26, review round 2 - blocker 2 + should-fix
 * 4). ONE `useDeferredAction` instance shared by every row in "Manage
 * segments" - "one countdown at a time" is enforced HERE (not just via the
 * dialog disabling other rows' buttons), so the round-1 bug (deleting A then
 * B under a single shared hook overwrote A's tracked state - A's own Cancel
 * cancelled B instead, and A's toast was orphaned with no `onCommitted`)
 * cannot reproduce even if a caller somehow bypasses the disabled button.
 */
import type { ReactElement } from 'react';
import { act, renderHook } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import type { ContactSegment } from '@/types/omnichannel';

const park = vi.fn();
const cancelPark = vi.fn();
const current = vi.fn();
vi.mock('@/services/pending-actions-service', () => ({
  pendingActionsService: {
    park: (...a: unknown[]) => park(...a),
    cancel: (...a: unknown[]) => cancelPark(...a),
    current: (...a: unknown[]) => current(...a),
  },
}));

let lastToastElement: ReactElement | null = null;
const toastCustom = vi.fn((renderFn: (id: string | number) => ReactElement) => {
  lastToastElement = renderFn('toast-id');
  return 'toast-id';
});
const toastDismiss = vi.fn();
const toastSuccess = vi.fn();
const toastError = vi.fn();
vi.mock('sonner', () => ({
  toast: {
    custom: (...a: [(id: string | number) => ReactElement]) => toastCustom(...a),
    dismiss: (...a: unknown[]) => toastDismiss(...a),
    success: (...a: unknown[]) => toastSuccess(...a),
    error: (...a: unknown[]) => toastError(...a),
  },
}));

import { useSegmentDeleteController } from './use-segment-delete-controller';

function segment(id: string): ContactSegment {
  return {
    id,
    workspaceId: 'wsp-1',
    name: `Segment ${id}`,
    description: null,
    filter: { kind: 'group', combinator: 'and', rules: [] },
    createdAt: '2026-01-01T00:00:00Z',
    updatedAt: '2026-01-01T00:00:00Z',
  };
}

function fireToastCancel(): void {
  const onCancel = (lastToastElement?.props as { onCancel?: () => void } | undefined)?.onCancel;
  onCancel?.();
}

beforeEach(() => {
  vi.clearAllMocks();
  lastToastElement = null;
  current.mockResolvedValue({ pending: null, lastOutcome: null });
});

describe('useSegmentDeleteController', () => {
  it('starts a delete - parks contact_segments.delete for the row', async () => {
    park.mockResolvedValue({
      id: 'pa1',
      commitAt: new Date(Date.now() + 10_000).toISOString(),
      windowSeconds: 10,
    });
    const { result } = renderHook(() => useSegmentDeleteController());

    await act(async () => {
      await result.current.startDelete(segment('seg-a'));
    });

    expect(park).toHaveBeenCalledWith('contact_segments.delete', 'contact_segment', 'seg-a', undefined);
    expect(result.current.deletingId).toBe('seg-a');
  });

  it('deleting A then attempting B while A is still counting down is a no-op - B never parks (blocker 2)', async () => {
    park.mockResolvedValue({
      id: 'pa1',
      commitAt: new Date(Date.now() + 10_000).toISOString(),
      windowSeconds: 10,
    });
    const { result } = renderHook(() => useSegmentDeleteController());

    await act(async () => {
      await result.current.startDelete(segment('seg-a'));
    });
    expect(result.current.deletingId).toBe('seg-a');

    await act(async () => {
      await result.current.startDelete(segment('seg-b'));
    });

    // Only the FIRST park call happened - B never started its own countdown,
    // so it can never overwrite A's tracked state.
    expect(park).toHaveBeenCalledTimes(1);
    expect(result.current.deletingId).toBe('seg-a');
  });

  it('two startDelete calls fired in the SAME tick only park once (round 3 fix - synchronous guard)', async () => {
    // `activeRef` (the round-2 guard) is set only after `await
    // deferred.start(...)` resolves - so two calls issued before that await
    // settles both used to read `activeRef.current === null` and both
    // parked. Model that race: park() doesn't resolve until we say so, and
    // BOTH startDelete calls fire before it does.
    let resolvePark: (value: { id: string; commitAt: string; windowSeconds: number }) => void = () => {};
    park.mockImplementation(
      () =>
        new Promise((resolve) => {
          resolvePark = resolve;
        }),
    );
    const { result } = renderHook(() => useSegmentDeleteController());

    let first!: Promise<void>;
    let second!: Promise<void>;
    act(() => {
      first = result.current.startDelete(segment('seg-a'));
      second = result.current.startDelete(segment('seg-b'));
    });

    resolvePark({ id: 'pa1', commitAt: new Date(Date.now() + 10_000).toISOString(), windowSeconds: 10 });
    await act(async () => {
      await first;
      await second;
    });

    // Only seg-a's park call happened - the second call was a synchronous
    // no-op, not a race that could overwrite the first's tracked state.
    expect(park).toHaveBeenCalledTimes(1);
    expect(park).toHaveBeenCalledWith('contact_segments.delete', 'contact_segment', 'seg-a', undefined);
    expect(result.current.deletingId).toBe('seg-a');
  });

  it("A's Cancel cancels A only, settling deletingId back to null", async () => {
    park.mockResolvedValue({
      id: 'pa1',
      commitAt: new Date(Date.now() + 10_000).toISOString(),
      windowSeconds: 10,
    });
    cancelPark.mockResolvedValue({ id: 'pa1', status: 'cancelled' });
    const { result } = renderHook(() => useSegmentDeleteController());

    await act(async () => {
      await result.current.startDelete(segment('seg-a'));
    });
    expect(result.current.deletingId).toBe('seg-a');

    await act(async () => {
      fireToastCancel();
    });

    expect(cancelPark).toHaveBeenCalledWith('pa1');
    expect(result.current.deletingId).toBeNull();
    expect(toastDismiss).toHaveBeenCalledWith('contact-segment-delete-seg-a');
  });

  it('after A commits, B becomes deletable and the caller is told to refresh', async () => {
    vi.useFakeTimers();
    try {
      park
        .mockResolvedValueOnce({
          id: 'pa1',
          commitAt: new Date(Date.now() + 10_000).toISOString(),
          windowSeconds: 10,
        })
        .mockResolvedValueOnce({
          id: 'pa2',
          commitAt: new Date(Date.now() + 10_000).toISOString(),
          windowSeconds: 10,
        });
      const onDeleted = vi.fn();
      const { result } = renderHook(() => useSegmentDeleteController(onDeleted));

      await act(async () => {
        await result.current.startDelete(segment('seg-a'));
      });
      expect(result.current.deletingId).toBe('seg-a');

      // The window lapses and the row committed server-side - the hook's own
      // 1s poll discovers it.
      current.mockResolvedValue({
        pending: null,
        lastOutcome: { id: 'pa1', actionKey: 'contact_segments.delete', status: 'committed', errorText: null },
      });
      await act(async () => {
        await vi.advanceTimersByTimeAsync(11_000);
      });

      expect(result.current.deletingId).toBeNull();
      expect(onDeleted).toHaveBeenCalledTimes(1);

      // B can now start its own countdown.
      await act(async () => {
        await result.current.startDelete(segment('seg-b'));
      });
      expect(park).toHaveBeenCalledWith('contact_segments.delete', 'contact_segment', 'seg-b', undefined);
      expect(result.current.deletingId).toBe('seg-b');
    } finally {
      vi.useRealTimers();
    }
  });
});
