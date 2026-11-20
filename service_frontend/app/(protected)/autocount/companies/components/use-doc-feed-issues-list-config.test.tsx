/**
 * sprint-5/14 S0 - red test for the doc-feed issues `ResourceList` config
 * (AC-14-94, AC-14-71). `use-doc-feed-issues-list-config.tsx` does not
 * exist yet - the dynamic import fails at runtime, the expected S0 red.
 */
import { renderHook } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

vi.mock('@/hooks/use-datetime', () => ({
  useDatetime: () => ({
    formatDate: (v: string) => v,
    formatDateTime: (v: string) => v,
    formatTime: (v: string) => v,
  }),
}));

const listDocFeedIssues = vi.fn();
vi.mock('@/services/autocount-service', () => ({
  autocountService: { listDocFeedIssues: (...a: unknown[]) => listDocFeedIssues(...a) },
}));

describe('useDocFeedIssuesListConfig (AC-14-71, 94)', () => {
  it('exposes columns for feed, DocNo, DocDate, kind, errors and attempts', async () => {
    const { useDocFeedIssuesListConfig } = await import('./use-doc-feed-issues-list-config');
    const { result } = renderHook(() => useDocFeedIssuesListConfig('co-1'));
    const columnIds = result.current.columns.map((c: { id?: string; accessorKey?: string }) => c.id ?? c.accessorKey);
    for (const expected of ['feed', 'docNo', 'docDate', 'kind', 'errors', 'attempts']) {
      expect(columnIds).toContain(expected);
    }
  });

  // sprint-5/14 S1 coder note: same fix as `use-doc-feed-runs-list-config.
  // test.tsx` - `segments`/`{key}` collides with the real (single-dimension,
  // tab-shaped) `ResourceListConfig.segments`; kind AND feed must be
  // selectable TOGETHER, so both are `filterFields` entries instead. The
  // shell's own search box (always on, `search` on the fetcher) IS the DocNo
  // search - `searchPlaceholder` names what it searches, there is no
  // separate "searchEnabled" toggle in the shell.
  it('offers kind and feed filters plus a DocNo search', async () => {
    const { useDocFeedIssuesListConfig } = await import('./use-doc-feed-issues-list-config');
    const { result } = renderHook(() => useDocFeedIssuesListConfig('co-1'));
    const config = result.current;
    expect(config.filterFields.some((f) => f.field === 'kind')).toBe(true);
    expect(config.filterFields.some((f) => f.field === 'feed')).toBe(true);
    expect(config.searchPlaceholder).toBeTruthy();
  });

  it('B1 (review round 2) - a row id is the backend `id`, never book/docKey (which the wire never sent)', async () => {
    const { useDocFeedIssuesListConfig } = await import('./use-doc-feed-issues-list-config');
    const { result } = renderHook(() => useDocFeedIssuesListConfig('co-1'));
    const row = {
      id: 'delivery_orders:db1:100', feed: 'delivery_orders', book: 'db1', docKey: 100,
      kind: 'failed', docNo: 'DO-100', docDate: '2026-09-29', sourceModifiedAt: null,
      errors: null, warnings: null, attempts: 1, firstAt: null, lastAt: null,
    } as const;
    expect(result.current.getRowId(row)).toBe('delivery_orders:db1:100');
  });
});
