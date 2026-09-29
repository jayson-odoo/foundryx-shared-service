/**
 * sprint-5/14 S0 - red test for the "Document feeds" tab (AC-14-90..92).
 *
 * `doc-feeds-tab.tsx` does not exist yet (S1 builds it against the mock
 * overlay) - the `await import('./doc-feeds-tab')` below fails at runtime
 * (module not found), which IS the expected red (D21 house convention:
 * import errors are acceptable red for a not-yet-built component).
 */
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';

// The Resource shell itself reads `next-auth/react`'s `useSession` directly
// (column-preference persistence) - unmocked, jsdom's fetch stub throws on
// the relative `/api/auth/session` URL (noisy but harmless); every other
// `ResourceList`-rendering test in this codebase stubs it the same way.
vi.mock('next-auth/react', () => ({
  useSession: () => ({ data: { user: { permissions: [] } }, status: 'authenticated' }),
}));

vi.mock('@/hooks/use-datetime', () => ({
  useDatetime: () => ({
    formatDate: (v: string) => v,
    formatDateTime: (v: string) => v,
    formatTime: (v: string) => v,
  }),
}));

vi.mock('@/hooks/use-can', () => ({
  useCan: () => ({ can: () => true, ready: true, permissions: new Set<string>(['autocount.sync.run']) }),
}));

const getDocFeeds = vi.fn();
const runDocFeed = vi.fn();
// sprint-5/14 S1 coder note: the tab ALSO mounts the runs + issues embedded
// lists straight away (D17's "stacks three embedded ResourceLists") - these
// two stub empty pages so the whole tab renders; only `getDocFeeds`/
// `runDocFeed` above are asserted on.
const listDocFeedRuns = vi.fn().mockResolvedValue({ data: [], total: 0, page: 0 });
const listDocFeedIssues = vi.fn().mockResolvedValue({ data: [], total: 0, page: 0 });
vi.mock('@/services/autocount-service', () => ({
  autocountService: {
    getDocFeeds: (...a: unknown[]) => getDocFeeds(...a),
    runDocFeed: (...a: unknown[]) => runDocFeed(...a),
    listDocFeedRuns: (...a: unknown[]) => listDocFeedRuns(...a),
    listDocFeedIssues: (...a: unknown[]) => listDocFeedIssues(...a),
  },
}));

function feedItem(over: Record<string, unknown> = {}) {
  return {
    feed: 'delivery_orders',
    book: 'db1',
    mode: 'off',
    connectionId: null,
    cursorDay: null,
    fullBackfillDoneAt: null,
    contractGate: null,
    retryableCount: 0,
    failedCount: 0,
    lastRun: null,
    backfill: null,
    ...over,
  };
}

describe('DocFeedsTab (AC-14-90)', () => {
  it('lists the three feeds with book, mode, waiting and failed counts', async () => {
    getDocFeeds.mockResolvedValue({
      feeds: [
        feedItem({ feed: 'delivery_orders', mode: 'push', retryableCount: 2, failedCount: 1 }),
        feedItem({ feed: 'goods_receive_notes' }),
        feedItem({ feed: 'branches' }),
      ],
      eligibleConnections: [],
    });
    const { DocFeedsTab } = await import('./doc-feeds-tab');

    render(<DocFeedsTab companyId="co-1" />);

    expect(await screen.findByText(/delivery orders/i)).toBeInTheDocument();
    expect(await screen.findByText(/goods receive notes/i)).toBeInTheDocument();
    expect(await screen.findByText(/branches/i)).toBeInTheDocument();
  });

  it('offers a Run now action gated by autocount.sync.run', async () => {
    getDocFeeds.mockResolvedValue({
      feeds: [feedItem({ feed: 'delivery_orders', mode: 'push' })],
      eligibleConnections: [],
    });
    const { DocFeedsTab } = await import('./doc-feeds-tab');

    render(<DocFeedsTab companyId="co-1" />);

    // Row actions render through the shell's `ActionMenu` (AC-14-92) - a "…"
    // trigger opening a menu, same as every other Resource-shell list (e.g.
    // `use-entities-list-config.tsx`'s row menu); its items render once
    // opened.
    // Longer timeout than the default 1000ms - under the FULL suite's
    // parallel load (429+ files) three embedded `ResourceList`s settling can
    // outrun the default (a real flake seen only in-suite, never isolated).
    const trigger = await screen.findByRole('button', { name: /actions/i }, { timeout: 5000 });
    await userEvent.click(trigger);
    expect(await screen.findByRole('menuitem', { name: /run now/i })).toBeInTheDocument();
  });

  it('S6 (review round 1) - hides Backfill while a stopped backfill is still open', async () => {
    getDocFeeds.mockResolvedValue({
      feeds: [
        feedItem({
          feed: 'delivery_orders', mode: 'push',
          backfill: {
            id: 'bf-1', status: 'stopped', dryRun: false,
            fromDay: '2023-01-01', toDay: '2026-09-29', nextDay: '2026-01-01',
            daysTotal: 100, daysDone: 10, error: 'boom',
          },
        }),
      ],
      eligibleConnections: [],
    });
    const { DocFeedsTab } = await import('./doc-feeds-tab');

    render(<DocFeedsTab companyId="co-1" />);

    const trigger = await screen.findByRole('button', { name: /actions/i }, { timeout: 5000 });
    await userEvent.click(trigger);
    // "Backfill" (start a NEW one) would always 409 (BACKFILL_OPEN) while a
    // `stopped` backfill still exists - only valid options are ever listed
    // (foolproof-UI). Resume/Discard cover a stopped backfill instead.
    expect(screen.queryByRole('menuitem', { name: /^backfill$/i })).not.toBeInTheDocument();
    expect(await screen.findByRole('menuitem', { name: /resume backfill/i })).toBeInTheDocument();
    expect(await screen.findByRole('menuitem', { name: /discard backfill/i })).toBeInTheDocument();
    // RS1 (review round 2) - Stop on an already-stopped backfill is a no-op.
    expect(screen.queryByRole('menuitem', { name: /stop backfill/i })).not.toBeInTheDocument();
  });

  it('RS1 (review round 2) - offers Stop backfill only while the backfill is running', async () => {
    getDocFeeds.mockResolvedValue({
      feeds: [
        feedItem({
          feed: 'delivery_orders', mode: 'push',
          backfill: {
            id: 'bf-1', status: 'running', dryRun: false,
            fromDay: '2023-01-01', toDay: '2026-09-29', nextDay: '2026-01-01',
            daysTotal: 100, daysDone: 10, error: null,
          },
        }),
      ],
      eligibleConnections: [],
    });
    const { DocFeedsTab } = await import('./doc-feeds-tab');

    render(<DocFeedsTab companyId="co-1" />);

    const trigger = await screen.findByRole('button', { name: /actions/i }, { timeout: 5000 });
    await userEvent.click(trigger);
    expect(await screen.findByRole('menuitem', { name: /stop backfill/i })).toBeInTheDocument();
    expect(screen.queryByRole('menuitem', { name: /resume backfill/i })).not.toBeInTheDocument();
  });
});
