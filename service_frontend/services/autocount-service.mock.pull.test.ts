/**
 * Pull state coverage (sprint-5/10, AC-10-48) - every pull state
 * `mockAutocountService` (the Vitest fixture double, exercised directly since
 * the S6 phase 2 swap retired the `withPhase1PullMock` runtime overlay - the
 * pull surface is real end to end now) must serve with no backend.
 */
import { beforeEach, describe, expect, it } from 'vitest';
import { ApiError } from '@/lib/api-client';
import { mockAutocountService, resetEtlMockState } from './autocount-service.mock';

beforeEach(() => resetEtlMockState());

describe('mockAutocountService - pull key states (AC-10-48)', () => {
  it('seeds one active and one revoked key', async () => {
    const keys = await mockAutocountService.listPullKeys();
    expect(keys.some((k) => k.revokedAt === null)).toBe(true);
    expect(keys.some((k) => k.revokedAt !== null)).toBe(true);
  });

  it('issuing a key returns the plaintext once, distinct from stored key data', async () => {
    const issued = await mockAutocountService.issuePullKey({ name: 'New key', companyIds: ['company-1'] });
    expect(issued.plaintext).toMatch(/^fxa_live_/);
    expect(issued.key).not.toHaveProperty('plaintext');
    const keys = await mockAutocountService.listPullKeys();
    expect(keys.some((k) => k.id === issued.key.id)).toBe(true);
  });

  it('a blank name 422s naming the field', async () => {
    await expect(mockAutocountService.issuePullKey({ name: '  ', companyIds: ['company-1'] })).rejects.toThrow(
      ApiError,
    );
  });

  it('revoking stamps revokedAt', async () => {
    const revoked = await mockAutocountService.revokePullKey('pull-key-active');
    expect(revoked.revokedAt).not.toBeNull();
  });
});

describe('mockAutocountService - pull snapshot states (AC-10-48)', () => {
  it('serves building / ready / failed / expired snapshots', async () => {
    const result = await mockAutocountService.listPullSnapshots({ page: 0, pageSize: 50 });
    const statuses = result.data.map((s) => s.status);
    expect(statuses).toContain('building');
    expect(statuses).toContain('ready');
    expect(statuses).toContain('failed');
    // The "expired" state is derived (expiresAt in the past), not a stored
    // status (AC-10-19) - pin the fixture itself carries a past expiresAt.
    const expired = result.data.find((s) => s.id === 'snap-product-expired');
    expect(expired).toBeDefined();
    expect(new Date(expired!.expiresAt as string).getTime()).toBeLessThan(Date.now());
  });

  it('a stock snapshot carries exclusions and negative pairs', async () => {
    const stock = await mockAutocountService.getPullSnapshot('snap-stock-ready');
    expect(stock.excludedCount).toBeGreaterThan(0);
    expect((stock.negativePairList ?? []).length).toBeGreaterThan(0);
  });

  it('a product snapshot carries the zero/negative/enrich-miss counters', async () => {
    const product = await mockAutocountService.getPullSnapshot('snap-product-ready');
    expect(product.zeroListPriceCount).toBeGreaterThan(0);
    expect(product.negativeListPriceCount).toBeGreaterThan(0);
    expect(product.enrichMissCount).toBeGreaterThanOrEqual(0);
  });

  it('an unknown snapshot id is a 404', async () => {
    await expect(mockAutocountService.getPullSnapshot('does-not-exist')).rejects.toThrow(ApiError);
  });

  it('a second build for the same (company, entity) while one is building re-attaches (AC-10-26)', async () => {
    const first = await mockAutocountService.buildPullSnapshot('company-1', 'product');
    // The seeded fixtures already carry a `building` product snapshot -
    // buildPullSnapshot re-attaches to it rather than minting a new id.
    const second = await mockAutocountService.buildPullSnapshot('company-1', 'product');
    expect(second.id).toBe(first.id);
  });

  it('a push+active pair 409s (review round 1 item 2; operator route, plain-string detail per pull.py, AC-10-31 scopes the structured ladder to the gateway only)', async () => {
    // `company-db`'s seeded `sales_order` task is `active`; its delivery
    // mode defaults to `push` (only `stock_balance` defaults `pull`,
    // sprint-5/13's `DEFAULT_PULL_ENTITY_TYPES` - unrelated to the push
    // gate), and it carries no in-flight snapshot of its
    // own, so the PUSH_ACTIVE guard - not the re-attach branch - is what
    // fires.
    await expect(mockAutocountService.buildPullSnapshot('company-db', 'sales_order')).rejects.toMatchObject({
      status: 409,
      message: expect.stringMatching(/flipped to automatic push/i),
    });
  });
});

describe('mockAutocountService - delivery mode (AC-10-11)', () => {
  it('requires a Sorento company code before enabling pull', async () => {
    // `company-1`'s default fixture carries no Sorento code.
    await expect(mockAutocountService.setDeliveryMode('company-1', 'stock_balance', 'pull')).rejects.toThrow(
      ApiError,
    );
  });

  it('a saved delivery mode is echoed back on the next getEtlTask (session state)', async () => {
    // `company-db` carries no Sorento code by default - give it one first,
    // the same prerequisite the Entities tab itself enforces.
    await mockAutocountService.updateSinkTarget('company-db', {
      sinkImpl: 'sorento',
      sinkConnectionId: 'conn-sink-1',
      sorentoCompanyCode: 'SRTD',
    });
    await mockAutocountService.setDeliveryMode('company-db', 'product', 'pull');
    const reloaded = await mockAutocountService.getEtlTask('company-db', 'product');
    expect(reloaded.deliveryMode).toBe('pull');
  });

  it('a never-touched non-pull-only entity defaults to push', async () => {
    const loaded = await mockAutocountService.getEtlTask('company-db', 'purchase_order');
    expect(loaded.deliveryMode).toBe('push');
  });
});
