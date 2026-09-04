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
