/**
 * Recipients tab list config (plan 29 S4, AC-BRD-10) - the state-filter
 * translation from a `FilterGroup` condition into the plain `RecipientQuery.
 * state` the real `broadcastService.recipients` GET expects, and the
 * `reload`/`reloadToken` seam the detail view's WS handler bumps to force
 * the embedded `<ResourceList>` to remount + refetch (no polling, plan
 * 29 S4).
 */
import { act, renderHook } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { useRecipientsListConfig } from './use-recipients-list-config';

vi.mock('@/hooks/use-datetime', () => ({
  useDatetime: () => ({ formatDateTime: (v: string) => v }),
}));

const recipientsMock = vi.fn().mockResolvedValue({ data: [], total: 0, page: 0 });
vi.mock('@/services/broadcast-service', () => ({
  broadcastService: {
    recipients: (...args: unknown[]) => recipientsMock(...args),
  },
}));

describe('useRecipientsListConfig', () => {
  it('passes no state filter when the query carries none', async () => {
    const { result } = renderHook(() => useRecipientsListConfig('wsp-1', 'bcst-1'));
    await act(async () => {
      await result.current.config.fetcher({ page: 0, pageSize: 25, filter: null });
    });
    expect(recipientsMock).toHaveBeenCalledWith('wsp-1', 'bcst-1', {
      page: 0,
      pageSize: 25,
      search: undefined,
      state: undefined,
    });
  });

  it('translates a `state eq X` filter condition into RecipientQuery.state', async () => {
    const { result } = renderHook(() => useRecipientsListConfig('wsp-1', 'bcst-1'));
    await act(async () => {
      await result.current.config.fetcher({
        page: 1,
        pageSize: 25,
        search: 'ali',
        filter: {
          kind: 'group',
          combinator: 'and',
          rules: [{ kind: 'condition', field: 'state', operator: 'eq', value: 'failed' }],
        },
      });
    });
    expect(recipientsMock).toHaveBeenCalledWith('wsp-1', 'bcst-1', {
      page: 1,
      pageSize: 25,
      search: 'ali',
      state: 'failed',
    });
  });

  it('returns an empty result with no service call while no broadcast is open yet', async () => {
    const { result } = renderHook(() => useRecipientsListConfig('wsp-1', null));
    recipientsMock.mockClear();
    const out = await result.current.config.fetcher({ page: 0, pageSize: 25 });
    expect(out).toEqual({ data: [], total: 0, page: 0 });
    expect(recipientsMock).not.toHaveBeenCalled();
  });

  it('reload() bumps reloadToken - the detail view keys the embedded list on it', () => {
    const { result } = renderHook(() => useRecipientsListConfig('wsp-1', 'bcst-1'));
    const before = result.current.reloadToken;
    act(() => result.current.reload());
    expect(result.current.reloadToken).toBe(before + 1);
  });
});
