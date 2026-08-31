import { describe, expect, it } from 'vitest';
import { computeMockNextRunTimes } from './autocount-service.mock';
import type { AutocountEtlSourceConfig } from '@/types/autocount';

function sourceConfig(over: Partial<AutocountEtlSourceConfig> = {}): AutocountEtlSourceConfig {
  return {
    connectionId: 'conn-sql-1',
    query: 'SELECT * FROM dbo.Debtor',
    lineQuery: null,
    keyColumns: ['AccNo'],
    watermarkColumn: null,
    comparedColumns: [],
    fromDate: null,
    docDateColumn: null,
    lineKeyColumn: null,
    lineProductColumn: null,
    lineWarehouseColumn: null,
    incrementalMinutes: 15,
    reconcileMode: 'dailyAt',
    reconcileHours: null,
    reconcileAt: '02:00',
    ...over,
  };
}

describe('computeMockNextRunTimes (plan 22 S3, PHASE 1 MOCK - mock/test only, S7)', () => {
  const now = new Date('2026-08-30T06:00:00Z');

  it('advances the incremental leg by the configured minutes', () => {
    const { nextIncrementalAt } = computeMockNextRunTimes(
      sourceConfig({ incrementalMinutes: 5, watermarkColumn: 'LastModified' }),
      now,
    );
    expect(nextIncrementalAt).toBe('2026-08-30T06:05:00.000Z');
  });

  it('floors a below-floor minutes value by watermark presence', () => {
    const noWatermark = computeMockNextRunTimes(
      sourceConfig({ incrementalMinutes: 2, watermarkColumn: null }),
      now,
    );
    expect(noWatermark.nextIncrementalAt).toBe('2026-08-30T06:15:00.000Z');

    const withWatermark = computeMockNextRunTimes(
      sourceConfig({ incrementalMinutes: 0, watermarkColumn: 'LastModified' }),
      now,
    );
    expect(withWatermark.nextIncrementalAt).toBe('2026-08-30T06:01:00.000Z');
  });

  it('interval reconcile mode advances by N hours (floored at 1)', () => {
    const { nextReconcileAt } = computeMockNextRunTimes(
      sourceConfig({ reconcileMode: 'interval', reconcileHours: 6 }),
      now,
    );
    expect(nextReconcileAt).toBe('2026-08-30T12:00:00.000Z');

    const floored = computeMockNextRunTimes(
      sourceConfig({ reconcileMode: 'interval', reconcileHours: 0 }),
      now,
    );
    expect(floored.nextReconcileAt).toBe('2026-08-30T07:00:00.000Z');
  });

  it('dailyAt reconcile mode lands on the next occurrence of HH:MM', () => {
    // 02:00 already passed for 06:00 "now" - rolls to the NEXT day.
    const rolledOver = computeMockNextRunTimes(sourceConfig({ reconcileMode: 'dailyAt', reconcileAt: '02:00' }), now);
    expect(rolledOver.nextReconcileAt).toBe('2026-08-31T02:00:00.000Z');

    // 18:00 is still ahead of "now" today.
    const laterToday = computeMockNextRunTimes(sourceConfig({ reconcileMode: 'dailyAt', reconcileAt: '18:00' }), now);
    expect(laterToday.nextReconcileAt).toBe('2026-08-30T18:00:00.000Z');
  });
});
