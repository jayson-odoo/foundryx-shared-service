/**
 * Lane L-D after #253: a Remove committed from the right-click / long-press row
 * menu (which reloads only the list) must also tell the Delivery page, whose
 * Push / Pull only state is built from the receivers it holds.
 */
import { renderHook } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { useReceiverList } from './use-receiver-list';

vi.mock('next-auth/react', () => ({
  useSession: () => ({ data: { user: { permissions: [] } }, status: 'authenticated' }),
}));
vi.mock('@/services/lead-capture-service', () => ({
  leadCaptureService: { listReceivers: vi.fn().mockResolvedValue([]), sendTestPush: vi.fn() },
}));

describe('useReceiverList', () => {
  it('a committed grace-window action refreshes the page state', () => {
    const onChanged = vi.fn();
    const { result } = renderHook(() => useReceiverList(vi.fn(), onChanged));
    expect(result.current.onDeferredCommitted).toBeTypeOf('function');
    result.current.onDeferredCommitted?.(['r1']);
    expect(onChanged).toHaveBeenCalledTimes(1);
  });
});
