import { renderHook } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import type { ListQuery } from '@/types/resource';

const listStaged = vi.fn();
vi.mock('@/services/autocount-service', () => ({
  autocountService: {
    listStaged: (...args: unknown[]) => listStaged(...args),
  },
}));

vi.mock('@/hooks/use-datetime', () => ({
  useDatetime: () => ({
    formatDate: (v: string) => v,
    formatDateTime: (v: string) => v,
    formatTime: (v: string) => v,
  }),
}));

const { useStagedListConfig } = await import('./use-staged-list-config');

function build(changed: boolean) {
  return renderHook(() =>
    useStagedListConfig({ jobId: 'job-1', changed, onOpenRecord: vi.fn() }),
  ).result.current;
}

beforeEach(() => {
  listStaged.mockReset().mockResolvedValue({ job: {}, data: [], total: 0, noChangeCount: 0 });
});

describe('staged list config (AC-15-10)', () => {
  it('is a Resource-shell config with a stable view key + a change marker column', () => {
    const c = build(true);
    expect(c.viewKey).toBe('autocount.staged.list');
    const ids = c.columns.map((col) => col.id);
    expect(ids).toContain('sourceRef');
    expect(ids).toContain('name');
    expect(ids).toContain('status');
    expect(ids).toContain('change');
  });

  it('opens the diff via a detail drawer (not forced inline)', () => {
    const onOpenRecord = vi.fn();
    const c = renderHook(() =>
      useStagedListConfig({ jobId: 'job-1', changed: true, onOpenRecord }),
    ).result.current;
    expect(c.rowHref({} as never)).toBe('#');
    expect(c.onRowSelect).toBeDefined();
  });

  it('server-paginates + passes search/changed/status through', async () => {
    const c = build(true);
    const query: ListQuery = {
      page: 2,
      pageSize: 50,
      search: 'acme',
      filter: {
        kind: 'group',
        combinator: 'and',
        rules: [{ kind: 'condition', field: 'status', operator: 'eq', value: 'FAILED' }],
      },
    };
    await c.fetcher(query);
    expect(listStaged).toHaveBeenCalledWith('job-1', {
      page: 2,
      pageSize: 50,
      search: 'acme',
      changed: true,
      status: 'FAILED',
    });
  });

  it('carries the changed=false partition for the no-change list', async () => {
    const c = build(false);
    await c.fetcher({ page: 0, pageSize: 25 });
    expect(listStaged.mock.calls[0][1]).toMatchObject({ changed: false });
  });

  it('offers a Status filter (a real Filters control, AC-15-10)', () => {
    const c = build(true);
    expect(c.filterFields.some((f) => f.field === 'status')).toBe(true);
  });
});
