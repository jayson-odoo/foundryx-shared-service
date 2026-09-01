import { renderHook } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import type { ListQuery } from '@/types/resource';

const push = vi.fn();
const listCompanies = vi.fn();
const listRuns = vi.fn();

vi.mock('next/navigation', () => ({
  useRouter: () => ({ push }),
}));

vi.mock('@/hooks/use-datetime', () => ({
  useDatetime: () => ({
    formatDate: (v: string) => v,
    formatDateTime: (v: string) => v,
    formatTime: (v: string) => v,
  }),
}));

vi.mock('@/services/autocount-service', () => ({
  autocountService: {
    listCompanies: (...args: unknown[]) => listCompanies(...args),
    listRuns: (...args: unknown[]) => listRuns(...args),
  },
}));

const { useAutocountCompaniesListConfig } = await import('./use-companies-list-config');
const { useAutocountRunsListConfig } = await import('./use-runs-list-config');

const QUERY: ListQuery = { page: 1, pageSize: 25 };

beforeEach(() => {
  push.mockReset();
  listCompanies.mockReset().mockResolvedValue({ data: [], total: 0, page: 0 });
  listRuns.mockReset().mockResolvedValue({ data: [], total: 0, page: 0 });
});

describe('companies list config', () => {
  it('is a Resource-shell config with a stable view key', () => {
    const { result } = renderHook(() => useAutocountCompaniesListConfig());
    expect(result.current.viewKey).toBe('autocount.companies.list');
    expect(result.current.columns.length).toBeGreaterThan(0);
  });

  it('navigates a row to the company detail', () => {
    const { result } = renderHook(() => useAutocountCompaniesListConfig());
    expect(
      result.current.rowHref({
        id: 'c1',
        connectionId: 'conn-1',
        databaseName: 'AED_VSOFT',
        companyName: 'V Soft',
        name: 'V Soft',
        isActive: true,
        sinkImpl: 'logging',
        sinkConnectionId: null,
        sorentoCompanyCode: null,
        createdAt: null,
      }),
    ).toBe('/autocount/companies/c1');
  });

  it('gates create behind the manage permission', () => {
    const { result } = renderHook(() => useAutocountCompaniesListConfig());
    expect(result.current.createPermission).toBe('autocount.companies.manage');
    result.current.onCreate?.();
    expect(push).toHaveBeenCalledWith('/autocount/companies/new');
  });

  it('has no Active|Trashed views - companies are not soft-trashed', () => {
    const { result } = renderHook(() => useAutocountCompaniesListConfig());
    expect(result.current.enableStatusViews).toBe(false);
  });

  it('fetches page-based, matching the endpoint contract', async () => {
    const { result } = renderHook(() => useAutocountCompaniesListConfig());
    await result.current.fetcher(QUERY);
    expect(listCompanies).toHaveBeenCalledWith({ page: 1, pageSize: 25 });
  });
});

describe('runs list config', () => {
  it('opens a run’s batch review, carrying the company as the back target', () => {
    const { result } = renderHook(() => useAutocountRunsListConfig('c1'));
    const href = result.current.rowHref({
      id: 'run-1',
      entityType: 'goods_received_note',
      jobId: 'job-9',
      windowFrom: null,
      windowTo: null,
      fetchedCount: 3,
      stagedCount: 3,
      failedCount: 0,
      pushedCount: 0,
      outcome: 'SUCCESS',
      error: null,
      truncated: false,
      watermarkAdvancedTo: null,
      startedAt: null,
      finishedAt: null,
      mode: 'manual',
      rowsScanned: 3,
      addedCount: 0,
      updatedCount: 0,
      deletedCount: 0,
      durationMs: 1200,
      skipReason: null,
    });
    expect(href).toBe(
      `/autocount/review/job-9?from=${encodeURIComponent('/autocount/companies/c1')}`,
    );
  });

  it('fetches runs scoped to its company', async () => {
    const { result } = renderHook(() => useAutocountRunsListConfig('c1'));
    await result.current.fetcher(QUERY);
    expect(listRuns).toHaveBeenCalledWith('c1', { page: 1, pageSize: 25 });
  });
});
