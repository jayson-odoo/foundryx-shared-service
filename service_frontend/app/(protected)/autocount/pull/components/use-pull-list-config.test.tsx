import { act, renderHook, waitFor } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import type { ListQuery } from '@/types/resource';
import type { AutocountCompany } from '@/types/autocount';

vi.mock('@/hooks/use-datetime', () => ({
  useDatetime: () => ({
    formatDate: (v: string) => v,
    formatDateTime: (v: string) => v,
    formatTime: (v: string) => v,
  }),
}));

const listPullKeys = vi.fn();
const listPullSnapshots = vi.fn();
vi.mock('@/services/autocount-service', () => ({
  autocountService: {
    listPullKeys: (...a: unknown[]) => listPullKeys(...a),
    listPullSnapshots: (...a: unknown[]) => listPullSnapshots(...a),
  },
}));

const { useAutocountPullListConfig } = await import('./use-pull-list-config');

const COMPANIES: AutocountCompany[] = [
  {
    id: 'c1',
    connectionId: 'conn-1',
    databaseName: 'AED',
    companyName: 'AED',
    name: 'AED Sorento',
    isActive: true,
    sinkImpl: 'sorento',
    sinkConnectionId: 'conn-2',
    sorentoCompanyCode: 'SRT',
    createdAt: null,
    sourceKind: 'http',
    documentPrerequisites: [],
  },
];

function config() {
  return renderHook(() =>
    useAutocountPullListConfig({ companies: COMPANIES, onIssueKey: vi.fn(), onBuildSnapshot: vi.fn() }),
  ).result;
}

describe('useAutocountPullListConfig (AC-10-38)', () => {
  it('the keys segment fetches keys and shapes rows as kind: "key"', async () => {
    listPullKeys.mockResolvedValueOnce([
      { id: 'k1', name: 'Prod', companyIds: ['c1'], keyPrefix: 'fxa_live_ab', createdAt: null, lastUsedAt: null, revokedAt: null },
    ]);
    const result = config();
    const query: ListQuery = { page: 0, pageSize: 25, segment: 'keys' };
    let page;
    await act(async () => {
      page = await result.current.fetcher(query);
    });
    expect(page!.data).toEqual([expect.objectContaining({ kind: 'key', id: 'k1' })]);
  });

  it('the snapshots segment fetches snapshots and shapes rows as kind: "snapshot"', async () => {
    listPullSnapshots.mockResolvedValueOnce({
      data: [{ id: 's1', entityType: 'product', companyId: 'c1', status: 'ready' }],
      total: 1,
      page: 0,
    });
    const result = config();
    const query: ListQuery = { page: 0, pageSize: 25, segment: 'snapshots' };
    let page;
    await act(async () => {
      page = await result.current.fetcher(query);
    });
    expect(page!.data).toEqual([expect.objectContaining({ kind: 'snapshot', id: 's1' })]);
  });

  it('columns swap entirely per segment - Keys carries name/companies, Snapshots carries entity/records', async () => {
    listPullKeys.mockResolvedValueOnce([]);
    listPullSnapshots.mockResolvedValueOnce({ data: [], total: 0, page: 0 });
    const result = config();

    await act(async () => {
      await result.current.fetcher({ page: 0, pageSize: 25, segment: 'keys' });
    });
    await waitFor(() => expect(result.current.columns.some((c) => c.id === 'name')).toBe(true));
    expect(result.current.columns.some((c) => c.id === 'records')).toBe(false);

    await act(async () => {
      await result.current.fetcher({ page: 0, pageSize: 25, segment: 'snapshots' });
    });
    await waitFor(() => expect(result.current.columns.some((c) => c.id === 'records')).toBe(true));
    expect(result.current.columns.some((c) => c.id === 'name')).toBe(false);
  });

  it('the create button label/handler follow the active segment', async () => {
    listPullSnapshots.mockResolvedValueOnce({ data: [], total: 0, page: 0 });
    const onIssueKey = vi.fn();
    const onBuildSnapshot = vi.fn();
    const { result } = renderHook(() =>
      useAutocountPullListConfig({ companies: COMPANIES, onIssueKey, onBuildSnapshot }),
    );
    await act(async () => {
      await result.current.fetcher({ page: 0, pageSize: 25, segment: 'snapshots' });
    });
    await waitFor(() => expect(result.current.createLabel).toBe('Build snapshot'));
    result.current.onCreate?.();
    expect(onBuildSnapshot).toHaveBeenCalled();
    expect(onIssueKey).not.toHaveBeenCalled();
  });

  it('Revoke is a deferred action, never a hand-rolled confirm (AC-10-38)', () => {
    const result = config();
    const revoke = result.current.actions.find((a) => a.id === 'revoke')!;
    expect(revoke.deferred).toEqual({
      actionKey: 'autocount_pull_api_key.revoke',
      entityType: 'autocount_pull_api_key',
    });
    expect(revoke.confirm).toBeUndefined();
  });

  it('getEntityId reads the raw backend id, not the shell-prefixed row id', () => {
    const result = config();
    expect(result.current.getEntityId?.({ kind: 'key', id: 'k1' } as never)).toBe('k1');
  });
});
