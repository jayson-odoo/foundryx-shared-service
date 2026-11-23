/**
 * Plan 72 (UAC S0-10) - "Counts by month" on the Doc Feeds run history: the
 * run-row menu item, the centred popup's month table, and the extra Counters
 * (needs review / skipped / switched off). Fake data only.
 */
import { fireEvent, render, renderHook, screen, within } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import type { DocFeedRun } from '@/types/autocount';
import { DocFeedMonthCountsDialog, monthLabel, monthRows } from './doc-feed-month-counts-dialog';

vi.mock('@/hooks/use-datetime', () => ({
  useDatetime: () => ({ formatDate: (v: string) => v, formatDateTime: (v: string) => v, formatTime: (v: string) => v }),
}));
vi.mock('@/services/autocount-service', () => ({ autocountService: { listDocFeedRuns: vi.fn() } }));

const run = (summary: DocFeedRun['summary']): DocFeedRun => ({
  id: 'r1', feed: 'project_registrations', kind: 'backfill', dryRun: true,
  dayFrom: '2006-01-01', dayTo: '2006-02-28', requests: 59, fetchedCount: 5,
  summary, outcome: 'SUCCESS', error: null, errorCode: null,
  startedAt: '2026-11-22T01:00:00Z', finishedAt: '2026-11-22T01:05:00Z', durationMs: 300000,
});

const backfill = run({
  created: 3, updated: 1, needsReview: 1, skipped: 1,
  byMonth: {
    '2006-02': { read: 2, created: 1, updated: 0, unchanged: 0, needsReview: 1, skipped: 0 },
    '2006-01': { read: 4, created: 2, updated: 1, unchanged: 0, needsReview: 0, skipped: 1 },
  },
});

describe('Counts by month popup', () => {
  it('lists months oldest first as mm/yyyy with a total row', () => {
    expect(monthRows(backfill).map(([m]) => m)).toEqual(['2006-01', '2006-02']);
    expect(monthLabel('2006-01')).toBe('01/2006');
    render(<DocFeedMonthCountsDialog run={backfill} onClose={() => {}} />);
    const grid = screen.getByTestId('doc-feed-month-counts');
    expect(within(grid).getByText('01/2006')).toBeInTheDocument();
    const headers = within(grid).getAllByRole('columnheader').map((h) => h.textContent);
    expect(headers).toEqual(['Month', 'Read', 'Created', 'Updated', 'Unchanged', 'Needs review', 'Skipped']);
    expect(screen.getByTestId('doc-feed-month-2006-01-read')).toHaveTextContent('4');
    expect(screen.getByTestId('doc-feed-month-total-read')).toHaveTextContent('6');
    expect(screen.getByTestId('doc-feed-month-total-needsReview')).toHaveTextContent('1');
  });

  it('closes from its Close button', () => {
    const onClose = vi.fn();
    render(<DocFeedMonthCountsDialog run={backfill} onClose={onClose} />);
    const closes = screen.getAllByRole('button', { name: 'Close' });
    fireEvent.click(closes.find((b) => b.textContent === 'Close') ?? closes[0]);
    expect(onClose).toHaveBeenCalled();
  });
});

describe('runs list config', () => {
  it('offers "Counts by month" in the row menu only for runs that carry month counts', async () => {
    const { useDocFeedRunsListConfig } = await import('./use-doc-feed-runs-list-config');
    const onMonthCounts = vi.fn();
    const { result } = renderHook(() => useDocFeedRunsListConfig('co-1', { onMonthCounts }));
    const action = (result.current.actions ?? []).find((a) => a.id === 'month-counts');
    expect(action?.label).toBe('Counts by month');
    expect(action?.surfaces.row).toBe(true);
    expect(action?.isVisible?.([backfill])).toBe(true);
    expect(action?.isVisible?.([run({ created: 1 })])).toBe(false);
    if (action && 'run' in action && action.run) action.run([backfill], { reload: () => {} });
    expect(onMonthCounts).toHaveBeenCalledWith(backfill);
    expect(result.current.columns.map((c) => c.id)).toContain('actions');
  });

  it('adds needs review, skipped and switched off to Counters', async () => {
    const { useDocFeedRunsListConfig } = await import('./use-doc-feed-runs-list-config');
    const { result } = renderHook(() => useDocFeedRunsListConfig('co-1'));
    const counters = result.current.columns.find((c) => c.id === 'summary') as unknown as { accessorFn: (r: DocFeedRun) => string };
    expect(counters.accessorFn(run({ created: 2, needsReview: 1, skipped: 3, switchedOff: 4 }))).toBe(
      '2 created, 0 updated, 0 unchanged, 1 needs review, 3 skipped, 4 switched off',
    );
    expect(result.current.columns.map((c) => c.id)).not.toContain('actions');
  });
});
