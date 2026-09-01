import { renderHook } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import type { AutocountSyncRun } from '@/types/autocount';

vi.mock('@/hooks/use-datetime', () => ({
  useDatetime: () => ({
    formatDate: (v: string) => v,
    formatDateTime: (v: string) => v,
    formatTime: (v: string) => v,
  }),
}));

const listRuns = vi.fn();
const listEtlRuns = vi.fn();
vi.mock('@/services/autocount-service', () => ({
  autocountService: {
    listRuns: (...a: unknown[]) => listRuns(...a),
    listEtlRuns: (...a: unknown[]) => listEtlRuns(...a),
  },
}));

const { useAutocountRunsListConfig } = await import('./use-runs-list-config');

function run(over: Partial<AutocountSyncRun> = {}): AutocountSyncRun {
  return {
    id: 'r1',
    entityType: 'customer',
    jobId: 'job-1',
    windowFrom: null,
    windowTo: null,
    fetchedCount: 2,
    stagedCount: 2,
    failedCount: 0,
    pushedCount: 2,
    outcome: 'SUCCESS',
    error: null,
    truncated: false,
    watermarkAdvancedTo: null,
    startedAt: '2026-08-30T06:32:00Z',
    finishedAt: '2026-08-30T06:32:01Z',
    mode: 'incremental',
    rowsScanned: 2,
    addedCount: 0,
    updatedCount: 2,
    deletedCount: 0,
    durationMs: 400,
    skipReason: null,
    ...over,
  };
}

beforeEach(() => {
  listRuns.mockReset().mockResolvedValue({ data: [], total: 0, page: 0 });
  listEtlRuns.mockReset().mockResolvedValue({ data: [], total: 0, page: 0 });
});

describe('runs list config - company variant (unchanged)', () => {
  it('keeps the company columns and fetches the company-wide history', async () => {
    const c = renderHook(() => useAutocountRunsListConfig('c1')).result.current;
    expect(c.viewKey).toBe('autocount.runs.list');
    expect(c.columns.map((col) => col.id)).toEqual([
      'entityType',
      'outcome',
      'counts',
      'finishedAt',
      'error',
    ]);
    await c.fetcher({ page: 0, pageSize: 25 });
    expect(listRuns).toHaveBeenCalledWith('c1', { page: 0, pageSize: 25 });
    expect(listEtlRuns).not.toHaveBeenCalled();
  });
});

describe('runs list config - task variant (plan 22 S2, AC-22-17)', () => {
  const cfg = () =>
    renderHook(() =>
      useAutocountRunsListConfig('c1', { variant: 'task', entityType: 'customer' }),
    ).result.current;

  it('is a Resource-shell config with the cost columns in order', () => {
    const c = cfg();
    expect(c.viewKey).toBe('autocount.task-runs.list');
    expect(c.enableStatusViews).toBe(false);
    expect(c.columns.map((col) => col.id)).toEqual([
      'startedAt',
      'mode',
      'rowsScanned',
      'addedCount',
      'updatedCount',
      'deletedCount',
      'failedCount',
      'durationMs',
      'outcome',
    ]);
  });

  it('fetches ONLY this entity through the task runs endpoint', async () => {
    await cfg().fetcher({ page: 1, pageSize: 10 });
    expect(listEtlRuns).toHaveBeenCalledWith('c1', 'customer', { page: 1, pageSize: 10 });
    expect(listRuns).not.toHaveBeenCalled();
  });

  it('opens the batch review for a run with a job and never navigates for a skipped tick', () => {
    const c = cfg();
    expect(c.rowHref(run())).toContain('/autocount/review/job-1');
    // Back returns to THIS task's Runs tab, not the company.
    expect(decodeURIComponent(c.rowHref(run()))).toContain('/entities/customer?tab=runs');
    expect(c.rowHref(run({ jobId: null, mode: 'skipped', outcome: 'SKIPPED' }))).toBe('#');
  });
});
