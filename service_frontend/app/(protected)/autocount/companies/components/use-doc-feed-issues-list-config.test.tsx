/**
 * sprint-5/14 S0 - red test for the doc-feed issues `ResourceList` config
 * (AC-14-94, AC-14-71). `use-doc-feed-issues-list-config.tsx` does not
 * exist yet - the dynamic import fails at runtime, the expected S0 red.
 */
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
    const config = useDocFeedIssuesListConfig('co-1');
    const columnIds = config.columns.map((c: { id?: string; accessorKey?: string }) => c.id ?? c.accessorKey);
    for (const expected of ['feed', 'docNo', 'docDate', 'kind', 'errors', 'attempts']) {
      expect(columnIds).toContain(expected);
    }
  });

  it('offers kind and feed filters plus a DocNo search', async () => {
    const { useDocFeedIssuesListConfig } = await import('./use-doc-feed-issues-list-config');
    const config = useDocFeedIssuesListConfig('co-1');
    expect(config.segments?.some((s: { key: string }) => s.key === 'kind')).toBe(true);
    expect(config.segments?.some((s: { key: string }) => s.key === 'feed')).toBe(true);
    expect(config.searchEnabled).toBe(true);
  });
});
