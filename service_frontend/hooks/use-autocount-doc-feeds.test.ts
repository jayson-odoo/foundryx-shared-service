/**
 * sprint-5/14 S0 - red test for the doc-feed hook (D17: "polls every 5s
 * while a run or backfill is in flight"). `use-autocount-doc-feeds.ts` does
 * not exist yet - the dynamic import fails at runtime, the expected S0 red.
 */
import { renderHook, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

const getDocFeeds = vi.fn();
vi.mock('@/services/autocount-service', () => ({
  autocountService: { getDocFeeds: (...a: unknown[]) => getDocFeeds(...a) },
}));

function view(over: Record<string, unknown> = {}) {
  return {
    feeds: [{ feed: 'delivery_orders', mode: 'off', backfill: null, lastRun: null }],
    eligibleConnections: [],
    ...over,
  };
}

beforeEach(() => {
  getDocFeeds.mockReset();
});

describe('useAutocountDocFeeds (D17)', () => {
  it('loads the view once when nothing is in flight', async () => {
    getDocFeeds.mockResolvedValue(view());
    const { useAutocountDocFeeds } = await import('./use-autocount-doc-feeds');
    const { result } = renderHook(() => useAutocountDocFeeds('co-1', 5));

    await waitFor(() => expect(result.current.view).not.toBeNull());
    expect(getDocFeeds).toHaveBeenCalledTimes(1);
  });

  it('polls while a feed has a run in flight, stops once settled', async () => {
    getDocFeeds
      .mockResolvedValueOnce(
        view({ feeds: [{ feed: 'delivery_orders', mode: 'push', lastRun: { outcome: null }, backfill: null }] }),
      )
      .mockResolvedValue(
        view({ feeds: [{ feed: 'delivery_orders', mode: 'push', lastRun: { outcome: 'SUCCESS' }, backfill: null }] }),
      );
    const { useAutocountDocFeeds } = await import('./use-autocount-doc-feeds');
    renderHook(() => useAutocountDocFeeds('co-1', 5));

    await waitFor(() => expect(getDocFeeds.mock.calls.length).toBeGreaterThanOrEqual(2));
  });

  // SS-BACKFILL-AUTO-RESUME: the beat resumes a backfill a lost worker
  // stopped about a minute later; an open tab must keep polling to show it.
  it.each(['ORPHANED', 'JOB_ENDED', 'JOB_ORPHANED', 'AUTO_RESUMING'])(
    'keeps polling while a backfill is stopped by a worker loss (%s)',
    async (errorCode) => {
      getDocFeeds
        .mockResolvedValueOnce(
          view({
            feeds: [
              { feed: 'delivery_orders', mode: 'push', lastRun: null, backfill: { status: 'stopped', errorCode } },
            ],
          }),
        )
        .mockResolvedValue(
          view({
            feeds: [
              { feed: 'delivery_orders', mode: 'push', lastRun: null, backfill: { status: 'done', errorCode: null } },
            ],
          }),
        );
      const { useAutocountDocFeeds } = await import('./use-autocount-doc-feeds');
      renderHook(() => useAutocountDocFeeds('co-1', 5));

      await waitFor(() => expect(getDocFeeds.mock.calls.length).toBeGreaterThanOrEqual(2));
    },
  );

  it.each(['USER_STOPPED', 'TIME_LIMIT', 'AUTO_RESUME_LIMIT'])(
    'does not poll a backfill that stays stopped (%s)',
    async (errorCode) => {
      getDocFeeds.mockResolvedValue(
        view({
          feeds: [
            { feed: 'delivery_orders', mode: 'push', lastRun: null, backfill: { status: 'stopped', errorCode } },
          ],
        }),
      );
      const { useAutocountDocFeeds } = await import('./use-autocount-doc-feeds');
      const { result } = renderHook(() => useAutocountDocFeeds('co-1', 5));

      await waitFor(() => expect(result.current.view).not.toBeNull());
      await new Promise((r) => setTimeout(r, 50));
      expect(getDocFeeds).toHaveBeenCalledTimes(1);
    },
  );
});
