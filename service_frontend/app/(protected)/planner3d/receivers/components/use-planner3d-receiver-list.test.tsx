/**
 * Lane PLANNER-3D-S1: the Receivers list - Remove is the grace-window action
 * (`planner3d_receivers.remove`), and a committed one refreshes the page.
 */
import { renderHook } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { usePlanner3dReceiverList } from './use-planner3d-receiver-list';

vi.mock('next-auth/react', () => ({
  useSession: () => ({ data: { user: { permissions: [] } }, status: 'authenticated' }),
}));
const listReceivers = vi.fn();
vi.mock('@/services/planner3d-service', () => ({
  planner3dService: { listReceivers: (...a: unknown[]) => listReceivers(...a) },
}));

describe('usePlanner3dReceiverList', () => {
  it('removes through the grace window and refreshes after a commit', () => {
    const onChanged = vi.fn();
    const { result } = renderHook(() => usePlanner3dReceiverList(vi.fn(), onChanged));
    const remove = result.current.actions?.find((a) => a.id === 'remove');
    expect(remove && 'deferred' in remove ? remove.deferred : null).toEqual({
      actionKey: 'planner3d_receivers.remove',
      entityType: 'planner3d_receiver',
    });
    result.current.onDeferredCommitted?.(['r1']);
    expect(onChanged).toHaveBeenCalledTimes(1);
  });

  it('lists the tenant receivers with event labels searchable', async () => {
    listReceivers.mockResolvedValue([
      {
        id: 'r1',
        url: 'https://crm.example.test/api/v1/public/planner/events',
        events: ['model.candidates_ready'],
        createdAt: '2026-11-27T00:00:00Z',
        lastSuccessAt: null,
      },
    ]);
    const { result } = renderHook(() => usePlanner3dReceiverList(vi.fn(), vi.fn()));
    const page = await result.current.fetcher({ page: 0, pageSize: 25, search: 'candidate' } as never);
    expect(page.data.map((r) => r.id)).toEqual(['r1']);
  });
});
