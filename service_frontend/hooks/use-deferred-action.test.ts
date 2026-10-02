/**
 * AC-DLA-43: the deferred-action state machine (idle -> pending -> committing
 * -> done|failed), cancel, and focus-poll parity - driven against the PHASE 1
 * mock service with fake timers so the window lapse is deterministic.
 */
import { act, renderHook } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import {
  mockPendingActionsService,
  resetMockPendingActions,
  setMockWindowSeconds,
} from '@/services/pending-actions-service.mock';

vi.mock('@/services/pending-actions-service', () => ({
  pendingActionsService: mockPendingActionsService,
}));

// Imported AFTER the mock so the hook module resolves the mocked service.
import { useDeferredAction } from './use-deferred-action';

beforeEach(() => {
  resetMockPendingActions();
  setMockWindowSeconds('destructive', 10);
  setMockWindowSeconds('reversible', 5);
  vi.useFakeTimers();
});

afterEach(() => {
  vi.useRealTimers();
});

describe('useDeferredAction', () => {
  it('starts idle', () => {
    const { result } = renderHook(() => useDeferredAction());
    expect(result.current.state.status).toBe('idle');
    expect(result.current.dimEntityIds).toEqual([]);
  });

  it('start() parks and transitions to pending with commitAt/windowSeconds', async () => {
    const { result } = renderHook(() => useDeferredAction());
    await act(async () => {
      await result.current.start('users.trash', { entityType: 'user', entityId: 'u1' });
    });
    expect(result.current.state.status).toBe('pending');
    if (result.current.state.status === 'pending') {
      expect(result.current.state.windowSeconds).toBe(10);
      expect(result.current.state.count).toBe(1);
      expect(new Date(result.current.state.commitAt).getTime()).toBeGreaterThan(Date.now());
    }
    expect(result.current.dimEntityIds).toEqual(['u1']);
  });

  it('commits after the window lapses and calls onCommitted', async () => {
    const onCommitted = vi.fn();
    const { result } = renderHook(() => useDeferredAction({ onCommitted }));
    await act(async () => {
      await result.current.start('users.trash', { entityType: 'user', entityId: 'u2' });
    });
    expect(result.current.state.status).toBe('pending');

    // Past the 10s window; the 1s poll tick discovers the commit.
    await act(async () => {
      await vi.advanceTimersByTimeAsync(11_000);
    });

    expect(result.current.state.status).toBe('done');
    expect(onCommitted).toHaveBeenCalledTimes(1);
    expect(result.current.dimEntityIds).toEqual([]);
  });

  it('cancel() restores idle without committing', async () => {
    const onCommitted = vi.fn();
    const { result } = renderHook(() => useDeferredAction({ onCommitted }));
    await act(async () => {
      await result.current.start('users.trash', { entityType: 'user', entityId: 'u3' });
    });
    await act(async () => {
      await result.current.cancel();
    });
    expect(result.current.state.status).toBe('idle');
    expect(result.current.dimEntityIds).toEqual([]);

    // Advancing well past the window must not commit a cancelled action.
    await act(async () => {
      await vi.advanceTimersByTimeAsync(11_000);
    });
    expect(onCommitted).not.toHaveBeenCalled();
  });

  it('bulk start() parks one row per entity behind ONE shared countdown (D13)', async () => {
    const { result } = renderHook(() => useDeferredAction());
    await act(async () => {
      await result.current.start('users.trash', [
        { entityType: 'user', entityId: 'u4' },
        { entityType: 'user', entityId: 'u5' },
        { entityType: 'user', entityId: 'u6' },
      ]);
    });
    expect(result.current.state.status).toBe('pending');
    if (result.current.state.status === 'pending') {
      expect(result.current.state.count).toBe(3);
    }
    expect(result.current.dimEntityIds).toEqual(['u4', 'u5', 'u6']);
  });

  it('watchFromMount picks up an action parked elsewhere (second-tab parity)', async () => {
    // Simulate a park that happened in "another tab" via the mock directly.
    await mockPendingActionsService.park('users.trash', 'user', 'u7');

    let result: ReturnType<typeof renderHook<ReturnType<typeof useDeferredAction>, unknown>>['result'];
    await act(async () => {
      ({ result } = renderHook(() =>
        useDeferredAction({ watchFromMount: true, watch: { entityType: 'user', entityId: 'u7' } }),
      ));
      // Flush the mount effect's async `checkCurrent` microtask.
      await Promise.resolve();
      await Promise.resolve();
    });

    expect(result!.current.state.status).toBe('pending');
    expect(result!.current.dimEntityIds).toEqual(['u7']);
  });

  it('bulk commit polls EVERY entity, not just the first (live-caught regression)', async () => {
    // Under eager dev there is no beat sweep - `current()` is what lazily
    // commits an overdue row, and it only touches the ONE record it asks
    // about. Polling only entities[0] left the rest of a bulk batch parked
    // forever (found live: a 3-row bulk delete removed only 1 row).
    setMockWindowSeconds('destructive', 5);
    const onCommitted = vi.fn();
    const { result } = renderHook(() => useDeferredAction({ onCommitted }));
    await act(async () => {
      await result.current.start('users.trash', [
        { entityType: 'user', entityId: 'b1' },
        { entityType: 'user', entityId: 'b2' },
        { entityType: 'user', entityId: 'b3' },
      ]);
    });

    await act(async () => {
      await vi.advanceTimersByTimeAsync(6_000);
    });

    expect(result.current.state.status).toBe('done');
    // Every row actually committed server-side, not just the first.
    const b1 = await mockPendingActionsService.current('user', 'b1');
    const b2 = await mockPendingActionsService.current('user', 'b2');
    const b3 = await mockPendingActionsService.current('user', 'b3');
    expect(b1.lastOutcome?.status).toBe('committed');
    expect(b2.lastOutcome?.status).toBe('committed');
    expect(b3.lastOutcome?.status).toBe('committed');
  });

  // ── fix round 1, item 2: a cancel outcome must never be reported as done ──

  it('a pending action cancelled from ANOTHER tab returns this hook to idle silently, not done', async () => {
    const onCommitted = vi.fn();
    const onCancelledElsewhere = vi.fn();
    const { result } = renderHook(() =>
      useDeferredAction({ onCommitted, onCancelledElsewhere }),
    );
    let parkId = '';
    await act(async () => {
      const parked = await result.current.start('users.trash', {
        entityType: 'user',
        entityId: 'ce1',
      });
      parkId = (await mockPendingActionsService.current('user', 'ce1')).pending!.id;
      expect(parked.windowSeconds).toBe(10);
    });

    // Simulate a SECOND tab/teammate cancelling the SAME pending action
    // directly against the server (bypassing this hook entirely).
    await act(async () => {
      await mockPendingActionsService.cancel(parkId);
    });

    // The next 1s poll tick discovers the cancellation.
    await act(async () => {
      await vi.advanceTimersByTimeAsync(1500);
    });

    expect(result.current.state.status).toBe('idle');
    expect(onCancelledElsewhere).toHaveBeenCalledTimes(1);
    expect(onCommitted).not.toHaveBeenCalled();
  });

  // ── fix round 1, item 3: Promise.allSettled - one 409 never orphans the rest

  it('bulk start() with one park rejecting keeps the rest tracked and reports the failure count', async () => {
    // Pre-park a DIFFERENT action on c2 so its park() call rejects (409).
    await mockPendingActionsService.park('roles.delete', 'user', 'c2');

    const { result } = renderHook(() => useDeferredAction());
    let outcome!: { commitAt: string; windowSeconds: number; failedCount: number };
    await act(async () => {
      outcome = await result.current.start('users.trash', [
        { entityType: 'user', entityId: 'c1' },
        { entityType: 'user', entityId: 'c2' },
        { entityType: 'user', entityId: 'c3' },
      ]);
    });

    expect(outcome.failedCount).toBe(1);
    expect(result.current.state.status).toBe('pending');
    if (result.current.state.status === 'pending') {
      expect(result.current.state.count).toBe(2);
    }
    expect(result.current.dimEntityIds).toEqual(['c1', 'c3']);

    // Cancel only touches the two rows that actually parked.
    await act(async () => {
      await result.current.cancel();
    });
    expect(result.current.state.status).toBe('idle');
    const c1 = await mockPendingActionsService.current('user', 'c1');
    const c3 = await mockPendingActionsService.current('user', 'c3');
    expect(c1.lastOutcome?.status).toBe('cancelled');
    expect(c3.lastOutcome?.status).toBe('cancelled');
  });

  // ── fix round 1, item 9: cancel() leaves pending synchronously and

  it('cancel() reconciles instead of hiding it when the cancel itself arrives too late', async () => {
    const onCommitted = vi.fn();
    const onCancelFailed = vi.fn();
    const { result } = renderHook(() => useDeferredAction({ onCommitted, onCancelFailed }));
    await act(async () => {
      await result.current.start('users.trash', { entityType: 'user', entityId: 'oc1' });
    });

    // Jump the clock past commitAt WITHOUT letting the 1s poll interval fire
    // (a real `advanceTimersByTimeAsync` would tick it) - simulates the
    // window closing between renders, before this tab's own poll notices.
    vi.setSystemTime(new Date(Date.now() + 11_000));

    let cancelPromise!: Promise<void>;
    act(() => {
      cancelPromise = result.current.cancel();
    });
    // Synchronous, optimistic exit - idle on the SAME tick, before the
    // reconciliation round-trip below even starts.
    expect(result.current.state.status).toBe('idle');

    await act(async () => {
      await cancelPromise;
    });

    // Reconciled: the action had already committed server-side, so the
    // caller is told via `onCommitted` (not left showing a false "cancelled"
    // for a record that's actually gone) plus an explicit cancel-failed toast.
    expect(onCancelFailed).toHaveBeenCalledTimes(1);
    expect(onCommitted).toHaveBeenCalledTimes(1);
  });

  // ── T5 fix round 2, B1: a `committing` `current()` response (the beat
  // sweep, or a racing poll from another tab, already CLAIMED the row - the
  // handler may still be running) must stay non-terminal: no toast, no
  // navigation, keep polling - until a genuinely terminal response arrives.

  it('a `committing` current() response stays non-terminal, then settles on the next terminal response', async () => {
    const onCommitted = vi.fn();
    const onFailed = vi.fn();
    const { result } = renderHook(() => useDeferredAction({ onCommitted, onFailed }));
    await act(async () => {
      await result.current.start('users.trash', { entityType: 'user', entityId: 'cm1' });
    });
    expect(result.current.state.status).toBe('pending');

    const currentSpy = vi.spyOn(mockPendingActionsService, 'current');
    currentSpy.mockResolvedValueOnce({
      pending: {
        id: 'pa-mid-commit',
        actionKey: 'users.trash',
        entityType: 'user',
        entityId: 'cm1',
        commitAt: new Date(Date.now() - 1000).toISOString(),
        windowSeconds: 10,
        requestedById: null,
        requestedByName: null,
        status: 'committing',
      },
      lastOutcome: null,
    });

    await act(async () => {
      await vi.advanceTimersByTimeAsync(1000);
    });
    // Still in flight - never reported done/failed off a `committing` row.
    expect(result.current.state.status).toBe('committing');
    expect(onCommitted).not.toHaveBeenCalled();
    expect(onFailed).not.toHaveBeenCalled();

    currentSpy.mockResolvedValueOnce({
      pending: null,
      lastOutcome: {
        id: 'pa-mid-commit',
        actionKey: 'users.trash',
        status: 'committed',
        errorText: null,
        endedAt: new Date().toISOString(),
      },
    });

    await act(async () => {
      await vi.advanceTimersByTimeAsync(1000);
    });
    expect(result.current.state.status).toBe('done');
    expect(onCommitted).toHaveBeenCalledTimes(1);

    currentSpy.mockRestore();
  });

  // ── N2: `onFailed` fires on a `failed` outcome - never a success toast ────

  it('a `failed` outcome calls onFailed, not onCommitted', async () => {
    const onCommitted = vi.fn();
    const onFailed = vi.fn();
    const { result } = renderHook(() => useDeferredAction({ onCommitted, onFailed }));
    await act(async () => {
      await result.current.start('users.trash', { entityType: 'user', entityId: 'fl1' });
    });

    const currentSpy = vi.spyOn(mockPendingActionsService, 'current').mockResolvedValueOnce({
      pending: null,
      lastOutcome: {
        id: 'pa-fail',
        actionKey: 'users.trash',
        status: 'failed',
        errorText: 'widget no longer exists',
        endedAt: new Date().toISOString(),
      },
    });

    await act(async () => {
      await vi.advanceTimersByTimeAsync(1000);
    });

    expect(result.current.state.status).toBe('failed');
    expect(onFailed).toHaveBeenCalledTimes(1);
    expect(onFailed).toHaveBeenCalledWith('widget no longer exists');
    expect(onCommitted).not.toHaveBeenCalled();

    currentSpy.mockRestore();
  });

  // ── N3: a `current()` that keeps ERRORING (e.g. a 404 after permission is
  // revoked mid-countdown) must not strand the hook in `pending` forever. ──

  it('current() erroring past the window settles failed after a grace, not stuck pending forever', async () => {
    const onCommitted = vi.fn();
    const onFailed = vi.fn();
    const { result } = renderHook(() => useDeferredAction({ onCommitted, onFailed }));
    await act(async () => {
      await result.current.start('users.trash', { entityType: 'user', entityId: 'err1' });
    });
    expect(result.current.state.status).toBe('pending');

    const currentSpy = vi
      .spyOn(mockPendingActionsService, 'current')
      .mockRejectedValue(new Error('network down'));

    // Past the 10s window - every poll from here on errors.
    await act(async () => {
      await vi.advanceTimersByTimeAsync(11_000);
    });
    // One post-lapse error alone is tolerated (grace).
    expect(result.current.state.status).toBe('pending');
    expect(onFailed).not.toHaveBeenCalled();

    await act(async () => {
      await vi.advanceTimersByTimeAsync(3_000);
    });

    expect(result.current.state.status).toBe('failed');
    expect(onFailed).toHaveBeenCalledWith("Could not confirm the action's outcome.");
    expect(onCommitted).not.toHaveBeenCalled();

    currentSpy.mockRestore();
  });

  it('current() erroring WHILE still counting down does not fail the action early', async () => {
    const onFailed = vi.fn();
    const { result } = renderHook(() => useDeferredAction({ onFailed }));
    await act(async () => {
      await result.current.start('users.trash', { entityType: 'user', entityId: 'err2' });
    });

    const currentSpy = vi
      .spyOn(mockPendingActionsService, 'current')
      .mockRejectedValue(new Error('blip'));

    // Well within the 10s window - errors here are just a blip, never fatal.
    await act(async () => {
      await vi.advanceTimersByTimeAsync(5_000);
    });
    expect(result.current.state.status).toBe('pending');
    expect(onFailed).not.toHaveBeenCalled();

    currentSpy.mockRestore();
  });

  it('reset() clears back to idle without touching the server', async () => {
    const { result } = renderHook(() => useDeferredAction());
    await act(async () => {
      await result.current.start('users.trash', { entityType: 'user', entityId: 'u8' });
    });
    act(() => result.current.reset());
    expect(result.current.state.status).toBe('idle');
    expect(result.current.dimEntityIds).toEqual([]);
  });
});
