import { describe, expect, it } from 'vitest';
import { computeMockNextRunTimes } from '@/lib/autocount-etl';
import type { AutocountEtlSourceConfig, AutocountEtlTask, AutocountService } from '@/types/autocount';
import { withPhase1NextRunMock } from './autocount-service.mock';

/**
 * The plan 22 S3 next-run overlay (`withPhase1NextRunMock`) is a TINY, tagged
 * PHASE 1 MOCK - unlike the S2 overlay it never touches `etlStatus`/
 * `activatedAt`/etc (those are already real). These pin the two behaviours
 * that make it safe to leave wrapping the shipped `.real` binding: every
 * OTHER call passes straight through untouched, and the two stamped fields
 * follow the REAL task's own `etlStatus` (null unless active).
 */

function sourceConfig(over: Partial<AutocountEtlSourceConfig> = {}): AutocountEtlSourceConfig {
  return {
    connectionId: 'conn-sql-1',
    query: 'SELECT * FROM dbo.Debtor',
    lineQuery: null,
    keyColumns: ['AccNo'],
    watermarkColumn: 'LastModified',
    comparedColumns: [],
    fromDate: null,
    incrementalMinutes: 5,
    reconcileMode: 'dailyAt',
    reconcileHours: null,
    reconcileAt: '02:00',
    ...over,
  };
}

function task(over: Partial<AutocountEtlTask> = {}): AutocountEtlTask {
  return {
    companyId: 'c1',
    entityType: 'customer',
    etlStatus: 'draft',
    activatedAt: null,
    sourceConfig: sourceConfig(),
    resultColumns: ['AccNo'],
    lastPreviewAt: null,
    lastRunAt: null,
    lastRunError: null,
    lastRunErrorCode: null,
    nextIncrementalAt: null,
    nextReconcileAt: null,
    ...over,
  };
}

/** A minimal stand-in for the real service - only the methods under test. */
function fakeReal(over: Partial<AutocountService> = {}): AutocountService {
  return {
    ...({} as AutocountService),
    getEtlTask: async () => task(),
    updateEtlTask: async () => task(),
    activateEtlTask: async () => task({ etlStatus: 'active' }),
    pauseEtlTask: async () => task({ etlStatus: 'paused' }),
    resumeEtlTask: async () => task({ etlStatus: 'active' }),
    ...over,
  };
}

describe('withPhase1NextRunMock (plan 22 S3)', () => {
  it('stamps null next-runs on a draft/paused task', async () => {
    const service = withPhase1NextRunMock(fakeReal({ getEtlTask: async () => task({ etlStatus: 'draft' }) }));
    const draft = await service.getEtlTask('c1', 'customer');
    expect(draft.nextIncrementalAt).toBeNull();
    expect(draft.nextReconcileAt).toBeNull();

    const service2 = withPhase1NextRunMock(
      fakeReal({ getEtlTask: async () => task({ etlStatus: 'paused' }) }),
    );
    const paused = await service2.getEtlTask('c1', 'customer');
    expect(paused.nextIncrementalAt).toBeNull();
    expect(paused.nextReconcileAt).toBeNull();
  });

  it('stamps computed next-runs on an active task (interval reconcile - a pure offset from "now")', async () => {
    const config = sourceConfig({ incrementalMinutes: 5, reconcileMode: 'interval', reconcileHours: 6 });
    const service = withPhase1NextRunMock(
      fakeReal({ getEtlTask: async () => task({ etlStatus: 'active', sourceConfig: config }) }),
    );
    const active = await service.getEtlTask('c1', 'customer');
    expect(active.nextIncrementalAt).not.toBeNull();
    expect(active.nextReconcileAt).not.toBeNull();
    // Interval mode is a pure offset from "now" on both legs, so the GAP
    // between them is deterministic regardless of exactly when "now" landed.
    const gapMs =
      Date.parse(active.nextReconcileAt as string) - Date.parse(active.nextIncrementalAt as string);
    expect(gapMs).toBe(6 * 3_600_000 - 5 * 60_000);
  });

  it('agrees with the standalone computeMockNextRunTimes helper for the same "now"', () => {
    const config = sourceConfig({ incrementalMinutes: 5, reconcileMode: 'dailyAt', reconcileAt: '18:00' });
    const now = new Date('2026-08-30T06:00:00Z');
    expect(computeMockNextRunTimes(config, now)).toEqual({
      nextIncrementalAt: '2026-08-30T06:05:00.000Z',
      nextReconcileAt: '2026-08-30T18:00:00.000Z',
    });
  });

  it('passes every other call straight through untouched', async () => {
    const listSqlConnections = async () => [];
    const service = withPhase1NextRunMock(fakeReal({ listSqlConnections }));
    expect(service.listSqlConnections).toBe(listSqlConnections);
  });

  it('stamps the task inside preview/run-now result wrappers too', async () => {
    const service = withPhase1NextRunMock(
      fakeReal({
        previewEtlTask: async () => ({
          task: task({ etlStatus: 'active' }),
          preview: { previewable: false, sink: 'logging', reason: 'x' },
        }),
        runEtlTaskNow: async () => ({
          runId: 'r1',
          jobId: 'j1',
          status: 'done',
          task: task({ etlStatus: 'active' }),
        }),
      }),
    );
    const preview = await service.previewEtlTask('c1', 'customer');
    expect(preview.task.nextIncrementalAt).not.toBeNull();
    const run = await service.runEtlTaskNow('c1', 'customer');
    expect(run.task.nextIncrementalAt).not.toBeNull();
  });
});
