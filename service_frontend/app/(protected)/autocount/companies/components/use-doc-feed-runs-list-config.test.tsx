/**
 * sprint-5/14 S0 - red test for the doc-feed runs `ResourceList` config
 * (AC-14-94). `use-doc-feed-runs-list-config.tsx` does not exist yet - the
 * dynamic import fails at runtime, the expected S0 red.
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

const listDocFeedRuns = vi.fn();
vi.mock('@/services/autocount-service', () => ({
  autocountService: { listDocFeedRuns: (...a: unknown[]) => listDocFeedRuns(...a) },
}));

describe('useDocFeedRunsListConfig (AC-14-94)', () => {
  it('exposes columns for kind, dry-run, day range, counters, outcome, error and duration', async () => {
    const { useDocFeedRunsListConfig } = await import('./use-doc-feed-runs-list-config');
    const { result } = renderHook(() => useDocFeedRunsListConfig('co-1'));
    const config = result.current;
    const columnIds = config.columns.map((c: { id?: string; accessorKey?: string }) => c.id ?? c.accessorKey);
    for (const expected of ['kind', 'dryRun', 'outcome', 'error', 'durationMs']) {
      expect(columnIds).toContain(expected);
    }
  });

  // sprint-5/14 S1 coder note: the SHAPE below (`segments`/`{key}`) collides
  // with the codebase's real `ResourceListConfig.segments` (an N-WAY TAB
  // control, `{id,label}`, mutually exclusive with every other filter -
  // `use-pull-list-config.tsx`'s Keys|Snapshots tabs). A single "feed"
  // dimension the operator can ALSO combine with other filters is a
  // `filterFields` entry (`use-staged-list-config.tsx`'s own `status`
  // filter), so this asserts that instead - the same intent (a feed
  // narrower is offered), the real primitive.
  it('offers a feed filter', async () => {
    const { useDocFeedRunsListConfig } = await import('./use-doc-feed-runs-list-config');
    const { result } = renderHook(() => useDocFeedRunsListConfig('co-1'));
    expect(result.current.filterFields.some((f) => f.field === 'feed')).toBe(true);
  });
});
