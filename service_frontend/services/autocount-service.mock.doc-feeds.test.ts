/**
 * sprint-5/14 S0 - red test for the mock doc-feed methods (D17, the pure
 * fixture seam). `mockAutocountService` exists already
 * (plan-13 precedent module); the new methods
 * (`getDocFeeds`/`updateDocFeed`/`runDocFeed`/`startDocFeedBackfill`/
 * `stopDocFeedBackfill`/`resumeDocFeedBackfill`/`discardDocFeedBackfill`/
 * `listDocFeedRuns`/`listDocFeedIssues`) do NOT exist yet - calling one is a
 * genuine runtime `TypeError` (not a function), the expected S0 red.
 */
import { describe, expect, it } from 'vitest';
import { mockAutocountService } from './autocount-service.mock';

describe('mockAutocountService doc-feed methods (sprint-5/14 D17)', () => {
  it('getDocFeeds answers two feeds, each off, for an unconfigured company (AC-14-46: branches is an entity now)', async () => {
    const view = await mockAutocountService.getDocFeeds('co-mock-1');
    expect(view.feeds).toHaveLength(2);
    expect(view.feeds.map((f) => f.feed).sort()).toEqual(['delivery_orders', 'goods_receive_notes'].sort());
    expect(view.feeds.every((f) => f.mode === 'off')).toBe(true);
  });

  it('updateDocFeed stores the connection and mode, and view() reflects it', async () => {
    await mockAutocountService.updateDocFeed('co-mock-1', 'delivery_orders', {
      connectionId: 'conn-mock-1', mode: 'dry_run',
    });
    const view = await mockAutocountService.getDocFeeds('co-mock-1');
    const item = view.feeds.find((f) => f.feed === 'delivery_orders');
    expect(item?.mode).toBe('dry_run');
  });

  it('runDocFeed records a run row surfaced by listDocFeedRuns', async () => {
    await mockAutocountService.updateDocFeed('co-mock-2', 'delivery_orders', {
      connectionId: 'conn-mock-1', mode: 'dry_run',
    });
    await mockAutocountService.runDocFeed('co-mock-2', 'delivery_orders', { kind: 'poll' });
    const runs = await mockAutocountService.listDocFeedRuns('co-mock-2', { feed: 'delivery_orders' });
    expect(runs.total).toBeGreaterThan(0);
  });

  it('startDocFeedBackfill then stopDocFeedBackfill flips the backfill state', async () => {
    await mockAutocountService.updateDocFeed('co-mock-3', 'delivery_orders', {
      connectionId: 'conn-mock-1', mode: 'push',
    });
    const started = await mockAutocountService.startDocFeedBackfill('co-mock-3', 'delivery_orders', {
      dryRun: true, fromDay: '2026-09-27', toDay: '2026-09-29',
    });
    expect(started.status).toBe('running');
    const stopped = await mockAutocountService.stopDocFeedBackfill('co-mock-3', 'delivery_orders');
    expect(stopped.status).toBe('stopped');
  });
});
