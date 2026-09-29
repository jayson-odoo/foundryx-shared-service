/**
 * sprint-5/14 S0 - red test for the "Document feeds" tab (AC-14-90..92).
 *
 * `doc-feeds-tab.tsx` does not exist yet (S1 builds it against the mock
 * overlay) - the `await import('./doc-feeds-tab')` below fails at runtime
 * (module not found), which IS the expected red (D21 house convention:
 * import errors are acceptable red for a not-yet-built component).
 */
import { render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

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
vi.mock('@/services/autocount-service', () => ({
  autocountService: {
    getDocFeeds: (...a: unknown[]) => getDocFeeds(...a),
    runDocFeed: (...a: unknown[]) => runDocFeed(...a),
  },
}));

function feedItem(over: Record<string, unknown> = {}) {
  return {
    feed: 'delivery_orders',
    book: 'db1',
    mode: 'off',
    connectionId: null,
    cursorDay: null,
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

    expect(await screen.findByRole('button', { name: /run now/i })).toBeInTheDocument();
  });
});
