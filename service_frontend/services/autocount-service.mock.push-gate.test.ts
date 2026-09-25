/**
 * Stock push gate PHASE 1 MOCK (sprint-5/13 S1, D18, AC-13-30/31/44) - the
 * pure mock (`mockAutocountService`, exercised directly by Vitest) AND the
 * scoped `withPhase1PushGateMock` overlay `autocount-service.ts` binds over
 * the REAL backend for every other surface. Both must serve all three gate
 * states with no backend (AC-13-44): open / contract / no_snapshot.
 */
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { ApiError } from '@/lib/api-client';
import type { AutocountCompanyDetail, AutocountEtlTask } from '@/types/autocount';
import type { AutocountService } from './autocount-service';
import {
  mockAutocountService as service,
  resetEtlMockState,
  setMockPushGate,
  withPhase1PushGateMock,
} from './autocount-service.mock';

beforeEach(() => resetEtlMockState());

async function rejected(promise: Promise<unknown>): Promise<ApiError> {
  try {
    await promise;
  } catch (e) {
    if (e instanceof ApiError) return e;
  }
  throw new Error('Expected an ApiError to be thrown.');
}

describe('mockAutocountService - stock push gate (AC-13-30)', () => {
  it('is shut (contract) by default for a never-configured company', async () => {
    const task = await service.getEtlTask('company-1', 'stock_balance');
    expect(task.pushGate).toEqual({ version: 2.4, requiredVersion: 2.5 });
  });

  it('opens once the company is on the Sorento sink with the sentinel code (STOCK25)', async () => {
    await service.updateSinkTarget('company-1', {
      sinkImpl: 'sorento',
      sinkConnectionId: 'conn-sink-1',
      sorentoCompanyCode: 'STOCK25',
    });
    const task = await service.getEtlTask('company-1', 'stock_balance');
    expect(task.pushGate).toBeNull();
  });

  it('stays shut on the Sorento sink with a code other than the sentinel', async () => {
    await service.updateSinkTarget('company-1', {
      sinkImpl: 'sorento',
      sinkConnectionId: 'conn-sink-1',
      sorentoCompanyCode: 'SRT',
    });
    const task = await service.getEtlTask('company-1', 'stock_balance');
    expect(task.pushGate).toEqual({ version: 2.4, requiredVersion: 2.5 });
  });

  it('is always null for a non-stock entity', async () => {
    const task = await service.getEtlTask('company-1', 'product');
    expect(task.pushGate).toBeNull();
  });

  it('setMockPushGate forces every one of the three states (AC-13-44)', async () => {
    setMockPushGate('company-1', 'open');
    expect((await service.getEtlTask('company-1', 'stock_balance')).pushGate).toBeNull();

    setMockPushGate('company-1', 'contract');
    expect((await service.getEtlTask('company-1', 'stock_balance')).pushGate).toEqual({
      version: 2.4,
      requiredVersion: 2.5,
    });

    setMockPushGate('company-1', 'no_snapshot');
    expect((await service.getEtlTask('company-1', 'stock_balance')).pushGate).toEqual({
      reason: 'no_snapshot',
    });
  });

  it('clearing the override (null) falls back to the sentinel-code default', async () => {
    setMockPushGate('company-1', 'open');
    setMockPushGate('company-1', null);
    // `company-1`'s default fixture carries a `logging` sink - falls back shut.
    expect((await service.getEtlTask('company-1', 'stock_balance')).pushGate).toEqual({
      version: 2.4,
      requiredVersion: 2.5,
    });
  });

  it('resetEtlMockState clears every override', async () => {
    setMockPushGate('company-1', 'open');
    resetEtlMockState();
    expect((await service.getEtlTask('company-1', 'stock_balance')).pushGate).toEqual({
      version: 2.4,
      requiredVersion: 2.5,
    });
  });
});

describe('mockAutocountService.setDeliveryMode - stock push (AC-13-31)', () => {
  it('refuses the push flip 422 while the gate is shut, naming the field', async () => {
    const err = await rejected(service.setDeliveryMode('company-1', 'stock_balance', 'push'));
    expect(err.status).toBe(422);
    expect(err.detail).toMatchObject({ fieldErrors: { deliveryMode: expect.any(String) } });
  });

  it('a no_snapshot refusal states the snapshot prerequisite', async () => {
    setMockPushGate('company-1', 'no_snapshot');
    const err = await rejected(service.setDeliveryMode('company-1', 'stock_balance', 'push'));
    expect(err.message).toMatch(/snapshot/i);
  });

  it('allows the push flip once the gate opens', async () => {
    setMockPushGate('company-1', 'open');
    const entity = await service.setDeliveryMode('company-1', 'stock_balance', 'push');
    expect(entity.entityType).toBe('stock_balance');
    const task = await service.getEtlTask('company-1', 'stock_balance');
    expect(task.deliveryMode).toBe('push');
  });

  it('never refuses a non-stock entity (unaffected by the gate)', async () => {
    await service.updateSinkTarget('company-db', {
      sinkImpl: 'sorento',
      sinkConnectionId: 'conn-sink-1',
      sorentoCompanyCode: 'SRTD',
    });
    const entity = await service.setDeliveryMode('company-db', 'product', 'pull');
    expect(entity.entityType).toBe('product');
  });
});

// ── withPhase1PushGateMock (the LIVE overlay `autocount-service.ts` binds) ──

/** A minimal fake `real` service - only the methods the overlay touches are
 * meaningful; everything else is a `vi.fn()` stub so `{...real}` type-checks
 * and an untouched call is loud (never silently mis-forwarded). */
function fakeReal(overrides: Partial<AutocountService> = {}): AutocountService {
  const detail = (companyId: string): AutocountCompanyDetail => ({
    company: {
      id: companyId,
      connectionId: 'conn-1',
      databaseName: 'DB',
      companyName: 'Co',
      name: 'Co',
      isActive: true,
      sinkImpl: 'sorento',
      sinkConnectionId: 'conn-sink-1',
      sorentoCompanyCode: 'STOCK25',
      createdAt: null,
      sourceKind: 'api',
      documentPrerequisites: [],
    },
    entities: [],
  });
  const bareTask = (entityType: string): AutocountEtlTask => ({
    companyId: 'c1',
    entityType,
    etlStatus: 'draft',
    activatedAt: null,
    sourceConfig: {
      connectionId: 'conn-1',
      query: '',
      lineQuery: null,
      keyColumns: [],
      watermarkColumn: null,
      comparedColumns: [],
      fromDate: null,
      docDateColumn: null,
      filterFormula: null,
      incrementalMinutes: 5,
      reconcileMode: 'dailyAt',
      reconcileHours: null,
      reconcileAt: '02:00',
    },
    resultColumns: [],
    lastPreviewAt: null,
    lastPreviewFailedCount: null,
    lastRunAt: null,
    lastRunError: null,
    lastRunErrorCode: null,
    nextIncrementalAt: null,
    nextReconcileAt: null,
  });
  const base = {
    getCompany: vi.fn(async (companyId: string) => detail(companyId)),
    getEtlTask: vi.fn(async (_companyId: string, entityType: string) => bareTask(entityType)),
    updateEtlTask: vi.fn(async (_c: string, entityType: string) => bareTask(entityType)),
    activateEtlTask: vi.fn(async (_c: string, entityType: string) => ({
      ...bareTask(entityType),
      etlStatus: 'active' as const,
    })),
    pauseEtlTask: vi.fn(async (_c: string, entityType: string) => ({
      ...bareTask(entityType),
      etlStatus: 'paused' as const,
    })),
    resumeEtlTask: vi.fn(async (_c: string, entityType: string) => ({
      ...bareTask(entityType),
      etlStatus: 'active' as const,
    })),
    setDeliveryMode: vi.fn(async () => ({ entityType: 'stock_balance' }) as never),
  };
  return { ...base, ...overrides } as unknown as AutocountService;
}

describe('withPhase1PushGateMock (sprint-5/13 S1 overlay, the ONE mocked surface)', () => {
  beforeEach(() => resetEtlMockState());

  it('attaches pushGate on getEtlTask for a stock_balance task, reading the REAL company', async () => {
    const overlay = withPhase1PushGateMock(fakeReal());
    const task = await overlay.getEtlTask('c1', 'stock_balance');
    // The fake real company carries the sentinel code -> gate opens.
    expect(task.pushGate).toBeNull();
  });

  it('never attaches pushGate for a non-stock entity, and never calls getCompany for it', async () => {
    const real = fakeReal();
    const overlay = withPhase1PushGateMock(real);
    const task = await overlay.getEtlTask('c1', 'product');
    expect(task.pushGate).toBeUndefined();
    expect(real.getCompany).not.toHaveBeenCalled();
  });

  it('setMockPushGate overrides the REAL company entirely (deterministic evidence states)', async () => {
    setMockPushGate('c1', 'contract');
    const overlay = withPhase1PushGateMock(fakeReal());
    const task = await overlay.getEtlTask('c1', 'stock_balance');
    expect(task.pushGate).toEqual({ version: 2.4, requiredVersion: 2.5 });
  });

  it('propagates pushGate through updateEtlTask/activate/pause/resume', async () => {
    setMockPushGate('c1', 'no_snapshot');
    const overlay = withPhase1PushGateMock(fakeReal());
    const update = await overlay.updateEtlTask('c1', 'stock_balance', {
      sourceConfig: { connectionId: 'conn-1' } as never,
    });
    expect(update.pushGate).toEqual({ reason: 'no_snapshot' });
    const activated = await overlay.activateEtlTask('c1', 'stock_balance');
    expect(activated.pushGate).toEqual({ reason: 'no_snapshot' });
    const paused = await overlay.pauseEtlTask('c1', 'stock_balance');
    expect(paused.pushGate).toEqual({ reason: 'no_snapshot' });
    const resumed = await overlay.resumeEtlTask('c1', 'stock_balance');
    expect(resumed.pushGate).toEqual({ reason: 'no_snapshot' });
  });

  it('setDeliveryMode(stock_balance, push) refuses 422 while the gate is shut, never reaching real', async () => {
    setMockPushGate('c1', 'contract');
    const real = fakeReal();
    const overlay = withPhase1PushGateMock(real);
    await expect(overlay.setDeliveryMode('c1', 'stock_balance', 'push')).rejects.toThrow(ApiError);
    expect(real.setDeliveryMode).not.toHaveBeenCalled();
  });

  it('setDeliveryMode(stock_balance, push) delegates to real once the gate opens', async () => {
    setMockPushGate('c1', 'open');
    const real = fakeReal();
    const overlay = withPhase1PushGateMock(real);
    await overlay.setDeliveryMode('c1', 'stock_balance', 'push');
    expect(real.setDeliveryMode).toHaveBeenCalledWith('c1', 'stock_balance', 'push');
  });

  it('setDeliveryMode always delegates for a non-stock entity, gate irrelevant', async () => {
    setMockPushGate('c1', 'contract');
    const real = fakeReal();
    const overlay = withPhase1PushGateMock(real);
    await overlay.setDeliveryMode('c1', 'product', 'push');
    expect(real.setDeliveryMode).toHaveBeenCalledWith('c1', 'product', 'push');
  });

  it('setDeliveryMode(stock_balance, pull) is never gated (the gate only guards the PUSH direction)', async () => {
    setMockPushGate('c1', 'contract');
    const real = fakeReal();
    const overlay = withPhase1PushGateMock(real);
    await overlay.setDeliveryMode('c1', 'stock_balance', 'pull');
    expect(real.setDeliveryMode).toHaveBeenCalledWith('c1', 'stock_balance', 'pull');
  });
});
