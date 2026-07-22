import { renderHook } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import type { ListQuery } from '@/types/resource';

vi.mock('@/hooks/use-datetime', () => ({
  useDatetime: () => ({
    formatDate: (v: string) => v,
    formatDateTime: (v: string) => v,
    formatTime: (v: string) => v,
  }),
}));

const listJobs = vi.fn().mockResolvedValue({ data: [], total: 0, page: 0 });
vi.mock('@/services/autocount-service', () => ({
  autocountService: {
    listJobs: (...args: unknown[]) => listJobs(...args),
  },
}));

const { useAutocountJobsListConfig } = await import('./use-jobs-list-config');

function cfg() {
  return renderHook(() => useAutocountJobsListConfig()).result.current;
}

describe('review jobs list config', () => {
  it('is a Resource-shell config, not a hand-rolled table', () => {
    const c = cfg();
    expect(c.viewKey).toBe('autocount.jobs.list');
    expect(c.columns.length).toBeGreaterThan(0);
    // N-way review segments replace the binary Active|Trashed views.
    expect(c.enableStatusViews).toBe(false);
  });

  it('surfaces the columns a batch row needs: company/entity/status/records/when', () => {
    const ids = cfg().columns.map((col) => col.id);
    expect(ids).toEqual(['company', 'entity', 'status', 'records', 'when']);
  });

  it('has Needs review | Done | All segments, defaulting to Needs review', () => {
    const c = cfg();
    expect(c.segments).toEqual([
      { id: 'needs_review', label: 'Needs review' },
      { id: 'done', label: 'Done' },
      { id: 'all', label: 'All' },
    ]);
    expect(c.defaultSegment).toBe('needs_review');
  });

  it('opens the batch review surface (form view) on row click', () => {
    const c = cfg();
    expect(c.rowHref({ jobId: 'job-9' } as never)).toBe('/autocount/review/job-9');
  });

  it('passes the selected segment to the backend as the status filter', async () => {
    const c = cfg();
    const query: ListQuery = { page: 2, pageSize: 25, segment: 'done' };
    await c.fetcher(query);
    expect(listJobs).toHaveBeenCalledWith({ page: 2, pageSize: 25, status: 'done' });
  });

  it('defaults the status filter to needs_review when no segment is set', async () => {
    listJobs.mockClear();
    await cfg().fetcher({ page: 0, pageSize: 25 });
    expect(listJobs).toHaveBeenCalledWith({ page: 0, pageSize: 25, status: 'needs_review' });
  });
});
