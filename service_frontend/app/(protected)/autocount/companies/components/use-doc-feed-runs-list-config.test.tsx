/**
 * sprint-5/14 S0 - red test for the doc-feed runs `ResourceList` config
 * (AC-14-94). `use-doc-feed-runs-list-config.tsx` does not exist yet - the
 * dynamic import fails at runtime, the expected S0 red.
 */
import type { ReactNode } from 'react';
import { render, renderHook, screen } from '@testing-library/react';
import type { DocFeedRun } from '@/types/autocount';
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

describe('summary null (crew DOCFEED-NULL-SUMMARY)', () => {
  const base = {
    id: 'r1',
    feed: 'delivery_orders',
    dryRun: false,
    dayFrom: null,
    dayTo: null,
    requests: 0,
    fetchedCount: 0,
    errorCode: null,
    startedAt: '2026-09-30T01:00:00Z',
  } as const;

  const runningRow: DocFeedRun = {
    ...base,
    id: 'r-running',
    kind: 'backfill',
    summary: null,
    outcome: null,
    error: null,
    finishedAt: null,
    durationMs: null,
  };
  const failedRow: DocFeedRun = {
    ...base,
    id: 'r-failed',
    kind: 'poll',
    summary: null,
    outcome: 'FAILED',
    error: 'Interrupted: the worker stopped before this run finished.',
    finishedAt: '2026-09-30T01:05:00Z',
    durationMs: 300000,
  };
  const pollRow: DocFeedRun = {
    ...base,
    id: 'r-poll',
    kind: 'poll',
    summary: { created: 2, updated: 1 },
    outcome: 'SUCCESS',
    error: null,
    finishedAt: '2026-09-30T01:05:00Z',
    durationMs: 1000,
  };
  const sweepRow: DocFeedRun = {
    ...base,
    id: 'r-sweep',
    kind: 'sweep',
    summary: { candidates: 3, deactivated: 1 },
    outcome: 'SUCCESS',
    error: null,
    finishedAt: '2026-09-30T01:05:00Z',
    durationMs: 1000,
  };

  async function summaryColumn() {
    const { useDocFeedRunsListConfig } = await import('./use-doc-feed-runs-list-config');
    const { result } = renderHook(() => useDocFeedRunsListConfig('co-1'));
    const column = result.current.columns.find((c) => c.id === 'summary');
    if (!column || typeof column.cell !== 'function' || !('accessorFn' in column) || !column.accessorFn) {
      throw new Error('summary column missing');
    }
    return column as typeof column & { accessorFn: (row: DocFeedRun, index: number) => unknown; cell: (ctx: never) => ReactNode };
  }

  it.each([
    ['running', runningRow],
    ['failed', failedRow],
  ])('accessor returns "-" for a %s row with a null summary', async (_name, run) => {
    const column = await summaryColumn();
    expect(column.accessorFn(run, 0)).toBe('-');
  });

  it.each([
    ['running', runningRow],
    ['failed', failedRow],
  ])('cell renders "-" for a %s row with a null summary', async (_name, run) => {
    const column = await summaryColumn();
    render(<>{column.cell({ row: { original: run } } as never)}</>);
    expect(screen.getByText('-')).toBeTruthy();
  });

  it('control: a poll row keeps its counters label', async () => {
    const column = await summaryColumn();
    expect(column.accessorFn(pollRow, 0)).toBe('2 created, 1 updated, 0 unchanged');
    render(<>{column.cell({ row: { original: pollRow } } as never)}</>);
    expect(screen.getByText('2 created, 1 updated, 0 unchanged')).toBeTruthy();
  });

  it('control: a sweep row keeps its candidates label', async () => {
    const column = await summaryColumn();
    expect(column.accessorFn(sweepRow, 0)).toBe('3 candidate(s), 1 deactivated, 0 not found');
    render(<>{column.cell({ row: { original: sweepRow } } as never)}</>);
    expect(screen.getByText('3 candidate(s), 1 deactivated, 0 not found')).toBeTruthy();
  });

  it('a re-check row leads with re-checked / changed, then its deletion counters', async () => {
    const column = await summaryColumn();
    const recheckRow: DocFeedRun = {
      ...sweepRow,
      summary: { rechecked: 120, changed: 2, updated: 2, candidates: 1, deactivated: 1, notFound: 0 },
    };
    expect(column.accessorFn(recheckRow, 0)).toBe(
      '120 re-checked, 2 changed, 1 candidate(s), 1 deactivated, 0 not found',
    );
  });

  it('labels the sweep kind as Re-check', async () => {
    const { docFeedRunKindLabel } = await import('../../components/autocount-meta');
    expect(docFeedRunKindLabel('sweep')).toBe('Re-check');
    expect(docFeedRunKindLabel('poll')).toBe('Poll');
  });
});
