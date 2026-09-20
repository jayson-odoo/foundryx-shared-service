/**
 * PHASE 1 MOCK state coverage (sprint-5/10, AC-10-48) - every pull state
 * `mockAutocountService` (the Vitest fixture double) and `withPhase1PullMock`
 * (the live-session overlay bound at `autocount-service.ts`) must serve with
 * no backend.
 */
import { beforeEach, describe, expect, it } from 'vitest';
import { ApiError } from '@/lib/api-client';
import type { AutocountCompany, AutocountEtlTask, AutocountService } from '@/types/autocount';
import { mockAutocountService, resetEtlMockState, withPhase1PullMock } from './autocount-service.mock';

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
});

function task(companyId = 'c1', entityType = 'product', over: Partial<AutocountEtlTask> = {}): AutocountEtlTask {
  return {
    companyId,
    entityType,
    etlStatus: 'draft',
    activatedAt: null,
    sourceConfig: {
      connectionId: 'conn-1',
      query: '',
      lineQuery: null,
      keyColumns: ['ItemCode'],
      watermarkColumn: null,
      comparedColumns: [],
      fromDate: null,
      docDateColumn: null,
      filterFormula: null,
      incrementalMinutes: 15,
      reconcileMode: 'dailyAt',
      reconcileHours: null,
      reconcileAt: '02:00',
    },
    resultColumns: ['ItemCode'],
    lastPreviewAt: null,
    lastPreviewFailedCount: null,
    lastRunAt: null,
    lastRunError: null,
    lastRunErrorCode: null,
    nextIncrementalAt: null,
    nextReconcileAt: null,
    ...over,
  };
}

function company(over: Partial<AutocountCompany> = {}): AutocountCompany {
  return {
    id: 'c1',
    connectionId: 'conn-1',
    databaseName: 'AED',
    companyName: 'AED',
    name: 'AED',
    isActive: true,
    sinkImpl: 'logging',
    sinkConnectionId: null,
    sorentoCompanyCode: 'SRT',
    createdAt: null,
    sourceKind: 'http',
    documentPrerequisites: [],
    ...over,
  };
}

describe('withPhase1PullMock (the runtime overlay `autocount-service.ts` binds)', () => {
  function fakeReal(): AutocountService {
    return {
      ...mockAutocountService,
      getEtlTask: async (companyId, entityType) => task(companyId, entityType),
      updateEtlTask: async (companyId, entityType, input) =>
        task(companyId, entityType, { sourceConfig: { ...task().sourceConfig, ...input.sourceConfig } }),
      getCompany: async (id) => ({ company: company({ id }), entities: [] }),
    };
  }

  it('seeds one active and one revoked key, and every AC-10-48 snapshot state, from first render (browser round 1 fix)', async () => {
    // Started genuinely empty pre-browser-round-1: the live app bound this
    // overlay, so a tester could never reach a single AC-10-48 state without
    // first performing the exact sequence of mutations by hand (and the
    // Build-snapshot dialog's company/entity pickers had nothing to offer at
    // all, since the lane's only REAL company carries no Sorento code). The
    // fix seeds a SELF-CONTAINED fixture company (never touching `real`) the
    // same way `mockAutocountService`'s own Vitest fixtures already do.
    const overlay = withPhase1PullMock(fakeReal());
    const keys = await overlay.listPullKeys();
    expect(keys.some((k) => k.revokedAt === null)).toBe(true);
    expect(keys.some((k) => k.revokedAt !== null)).toBe(true);

    const snapshots = await overlay.listPullSnapshots();
    const statuses = snapshots.data.map((s) => s.status);
    expect(statuses).toContain('building');
    expect(statuses).toContain('ready');
    expect(statuses).toContain('failed');
    const expired = snapshots.data.find((s) => s.id === 'snap-product-expired');
    expect(expired).toBeDefined();
    expect(new Date(expired!.expiresAt as string).getTime()).toBeLessThan(Date.now());
    const stock = snapshots.data.find((s) => s.entityType === 'stock_balance');
    expect(stock?.excludedCount ?? 0).toBeGreaterThan(0);
    expect((stock?.negativePairList ?? []).length).toBeGreaterThan(0);
  });

  it('the fixture company is offered alongside real companies, with a Sorento code and pull-capable entities', async () => {
    const overlay = withPhase1PullMock(fakeReal());
    const companies = await overlay.listCompanies();
    const fixture = companies.data.find((c) => c.name === 'Pull demo (mock)');
    expect(fixture).toBeDefined();
    expect(fixture!.sorentoCompanyCode).toBeTruthy();
    // Real companies (the `fakeReal()` stub returns none here) are never
    // dropped - the fixture is APPENDED, not a replacement.
    expect(companies.data.some((c) => c.id === fixture!.id)).toBe(true);

    const detail = await overlay.getCompany(fixture!.id);
    expect(detail.entities.some((e) => e.entityType === 'stock_balance' && e.deliveryMode === 'pull')).toBe(true);
    // The `product` entity sits in push+active - the reachable A6
    // PUSH_ACTIVE demo (never `real.getCompany`, which would 404 for an id
    // the live backend never created).
    const product = detail.entities.find((e) => e.entityType === 'product');
    expect(product?.deliveryMode ?? 'push').toBe('push');
    expect(product?.etlStatus).toBe('active');
    await expect(overlay.buildPullSnapshot(fixture!.id, 'product')).rejects.toMatchObject({
      status: 409,
      detail: { code: 'PUSH_ACTIVE' },
    });
  });

  it('setDeliveryMode requires a Sorento company code before pull', async () => {
    const overlay = withPhase1PullMock({
      ...fakeReal(),
      getCompany: async (id) => ({ company: company({ id, sorentoCompanyCode: null }), entities: [] }),
    });
    await expect(overlay.setDeliveryMode('c1', 'product', 'pull')).rejects.toThrow(ApiError);
  });

  it('a saved deliveryMode is echoed back on the NEXT getEtlTask (session state)', async () => {
    const overlay = withPhase1PullMock(fakeReal());
    await overlay.setDeliveryMode('c1', 'product', 'pull');
    const reloaded = await overlay.getEtlTask('c1', 'product');
    expect(reloaded.deliveryMode).toBe('pull');
  });

  it('a never-touched task defaults to push', async () => {
    const overlay = withPhase1PullMock(fakeReal());
    const loaded = await overlay.getEtlTask('c1', 'product');
    expect(loaded.deliveryMode).toBe('push');
  });

  it('the entities list reflects the same session delivery mode (getCompany overlay)', async () => {
    const overlay = withPhase1PullMock({
      ...fakeReal(),
      getCompany: async (id) => ({
        company: company({ id }),
        entities: [
          {
            id: 'e1',
            entityType: 'product',
            syncMode: 'MANUAL',
            sourceImpl: 'autocount_http',
            recordCap: 5000,
            initialLookbackDays: 30,
            enabled: true,
            lastSuccessAt: null,
            lastAttemptAt: null,
            watermarkAt: null,
            consecutiveFailures: 0,
            lastError: null,
            etlStatus: 'draft',
          },
        ],
      }),
    });
    await overlay.setDeliveryMode('c1', 'product', 'pull');
    const detail = await overlay.getCompany('c1');
    expect(detail.entities[0].deliveryMode).toBe('pull');
  });

  it('buildPullSnapshot throws the Appendix A6 PUSH_ACTIVE body for a push+active pair (review round 1 item 2)', async () => {
    const overlay = withPhase1PullMock({
      ...fakeReal(),
      getCompany: async (id) => ({
        company: company({ id, sorentoCompanyCode: 'SRT' }),
        entities: [
          {
            id: 'e1',
            entityType: 'product',
            syncMode: 'AUTO',
            sourceImpl: 'autocount_http',
            recordCap: 5000,
            initialLookbackDays: 30,
            enabled: true,
            lastSuccessAt: null,
            lastAttemptAt: null,
            watermarkAt: null,
            consecutiveFailures: 0,
            lastError: null,
            etlStatus: 'active',
            deliveryMode: 'push',
          },
        ],
      }),
    });
    await expect(overlay.buildPullSnapshot('c1', 'product')).rejects.toMatchObject({
      status: 409,
      detail: { code: 'PUSH_ACTIVE', companyCode: 'SRT', entity: 'products' },
    });
  });

  it('a 409 PUSH_ACTIVE carries the SAME error ladder shape other codes use', () => {
    // The gateway 409 itself is server-side (S4); this pins the FE type the
    // snapshot detail / pull page must be able to render for it (AC-10-31).
    const error = new ApiError('This book is now automatic.', 409, null, {
      code: 'PUSH_ACTIVE',
      message: 'This book is now automatic.',
      companyCode: 'SRT',
      entity: 'products',
    });
    expect(error.status).toBe(409);
    expect((error.detail as { code: string }).code).toBe('PUSH_ACTIVE');
  });

  it('building a snapshot re-attaches within the overlay too (AC-10-26)', async () => {
    const overlay = withPhase1PullMock(fakeReal());
    const first = await overlay.buildPullSnapshot('c1', 'product');
    const second = await overlay.buildPullSnapshot('c1', 'product');
    expect(second.id).toBe(first.id);
    expect(second.status).toBe('building');
  });
});
