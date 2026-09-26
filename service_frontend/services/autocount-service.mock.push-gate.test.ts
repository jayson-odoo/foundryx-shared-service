/**
 * Stock push gate mock fixture (sprint-5/13, D18, AC-13-30/31/44) - the pure
 * mock (`mockAutocountService`, exercised directly by Vitest) must serve all
 * three gate states with no backend (AC-13-44): open / contract /
 * no_snapshot. sprint-5/13 S3 retired the `withPhase1PushGateMock` overlay
 * that once stood in front of the REAL backend - `autocount-service.ts`
 * reads `pushGate` straight off the wire now.
 */
import { beforeEach, describe, expect, it } from 'vitest';
import { ApiError } from '@/lib/api-client';
import { mockAutocountService as service, resetEtlMockState, setMockPushGate } from './autocount-service.mock';

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
