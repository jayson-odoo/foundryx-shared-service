/**
 * sprint-5/14 S0 - red test for the doc-feed runs `ResourceList` config
 * (AC-14-94). `use-doc-feed-runs-list-config.tsx` does not exist yet - the
 * dynamic import fails at runtime, the expected S0 red.
 */
import { describe, expect, it, vi } from 'vitest';

vi.mock('@/hooks/use-datetime', () => ({
  useDatetime: () => ({
    formatDate: (v: string) => v,
    formatDateTime: (v: string) => v,
    formatTime: (v: string) => v,
  }),
}));

const listDocFeedRuns = vi.fn();
vi.mock('@/services/autocount-service', () => ({
  autocountService: { listDocFeedRuns: (...a: unknown[]) => listDocFeedRuns(...a) },
}));

describe('useDocFeedRunsListConfig (AC-14-94)', () => {
  it('exposes columns for kind, dry-run, day range, counters, outcome, error and duration', async () => {
    const { useDocFeedRunsListConfig } = await import('./use-doc-feed-runs-list-config');
    const config = useDocFeedRunsListConfig('co-1');
    const columnIds = config.columns.map((c: { id?: string; accessorKey?: string }) => c.id ?? c.accessorKey);
    for (const expected of ['kind', 'dryRun', 'outcome', 'error', 'durationMs']) {
      expect(columnIds).toContain(expected);
    }
  });

  it('offers a feed filter as a SearchSelect segment', async () => {
    const { useDocFeedRunsListConfig } = await import('./use-doc-feed-runs-list-config');
    const config = useDocFeedRunsListConfig('co-1');
    expect(config.segments?.some((s: { key: string }) => s.key === 'feed')).toBe(true);
  });
});
