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
    filterFormula: null,
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

// ── plan sprint-5/01 S1 - DB-only company (PHASE 1 MOCK is the backend spec) ──
import { beforeEach } from 'vitest';
import { ApiError } from '@/lib/api-client';
import type { AutocountEntityConfig } from '@/types/autocount';
import {
  computeDocumentPrerequisites,
  mockAutocountService as service,
  resetEtlMockState,
} from './autocount-service.mock';

async function rejected(p: Promise<unknown>): Promise<ApiError> {
  try {
    await p;
  } catch (e) {
    expect(e).toBeInstanceOf(ApiError);
    return e as ApiError;
  }
  throw new Error('expected a rejection');
}

function row(entityType: string, over: Partial<AutocountEntityConfig> = {}): AutocountEntityConfig {
  return {
    id: entityType,
    entityType,
    syncMode: 'AUTO',
    sourceImpl: 'sql_db',
    recordCap: 200,
    initialLookbackDays: 30,
    enabled: true,
    lastSuccessAt: null,
    lastAttemptAt: null,
    watermarkAt: null,
    consecutiveFailures: 0,
    lastError: null,
    etlStatus: 'active',
    ...over,
  };
}

describe('mock DB company - create dispatcher (AC-01-01/02/04/05)', () => {
  beforeEach(() => resetEtlMockState());

  it('lists the API company and the seeded DB company with their derived sourceKind', async () => {
    const list = await service.listCompanies();
    const kinds = Object.fromEntries(list.data.map((c) => [c.id, c.sourceKind]));
    expect(kinds['company-1']).toBe('api');
    expect(kinds['company-db']).toBe('db');
    // The LIST carries no prerequisites (detail only).
    for (const c of list.data) expect(c.documentPrerequisites).toEqual([]);
  });

  it('creates a DB company from an unbound sql_database connection - identity from its database', async () => {
    const company = await service.createCompany({ connectionId: 'conn-sql-2', name: '' });
    expect(company.sourceKind).toBe('db');
    expect(company.connectionId).toBe('conn-sql-2');
    expect(company.databaseName).toBe('AED_BRANCH');
    // dbo.Profile read best-effort; the label falls back to it when blank.
    expect(company.companyName).toBe('Sorento Trading (Branch) Sdn Bhd');
    expect(company.name).toBe('Sorento Trading (Branch) Sdn Bhd');
    const list = await service.listCompanies();
    expect(list.data.map((c) => c.id)).toContain(company.id);
  });

  it('honours the operator label when given', async () => {
    const company = await service.createCompany({ connectionId: 'conn-sql-2', name: ' Branch ' });
    expect(company.name).toBe('Branch');
  });

  it('409s a connection already bound to a company, naming it', async () => {
    const err = await rejected(service.createCompany({ connectionId: 'conn-sql-1', name: '' }));
    expect(err.status).toBe(409);
    expect(err.message).toBe("'AED_Sorento_2024' is already connected as company 'Sorento Trading'.");
  });

  it('409s a database already connected as an API company (one company per database, D14)', async () => {
    const err = await rejected(service.createCompany({ connectionId: 'conn-sql-vsoft', name: '' }));
    expect(err.status).toBe(409);
    expect(err.message).toBe("'AED_VSOFT' is already connected as company 'AED VSoft'.");
  });

  it('422s on connectionId when the probe cannot connect - sanitized, on the field', async () => {
    const err = await rejected(service.createCompany({ connectionId: 'conn-sql-down', name: '' }));
    expect(err.status).toBe(422);
    expect(err.detail).toEqual({ fieldErrors: { connectionId: expect.any(String) } });
    expect(err.message).not.toContain('conn-sql-down');
  });

  it('a non-SQL connection still takes the API path (unchanged scaffolding)', async () => {
    const company = await service.createCompany({ connectionId: 'conn-autocount-1', name: '' });
    expect(company.sourceKind).toBe('api');
  });

  it('a freshly created DB company has NO seeded entities (AC-01-05)', async () => {
    const company = await service.createCompany({ connectionId: 'conn-sql-2', name: '' });
    const detail = await service.getCompany(company.id);
    expect(detail.entities).toEqual([]);
    expect(detail.company.documentPrerequisites).toEqual([]);
  });

  it('the API company still seeds its customer row on the API path (regression pin)', async () => {
    const detail = await service.getCompany('company-1');
    expect(detail.entities.map((e) => [e.entityType, e.sourceImpl])).toEqual([
      ['customer', 'autocount_read'],
    ]);
  });
});

describe('mock DB company - document prerequisites (AC-01-11)', () => {
  beforeEach(() => resetEtlMockState());

  it('the seeded in-use DB company reports one inactive-only and one missing+inactive line', async () => {
    const detail = await service.getCompany('company-db');
    expect(detail.entities.every((e) => e.sourceImpl === 'sql_db')).toBe(true);
    expect(detail.company.documentPrerequisites).toEqual([
      { entityType: 'sales_order', missing: [], inactive: ['product'] },
      { entityType: 'purchase_order', missing: ['supplier'], inactive: ['product'] },
    ]);
  });

  it('computeDocumentPrerequisites - none configured → []', () => {
    expect(computeDocumentPrerequisites([row('customer'), row('product')])).toEqual([]);
  });

  it('computeDocumentPrerequisites - all active → empty missing/inactive per document', () => {
    expect(
      computeDocumentPrerequisites([
        row('customer'), row('supplier'), row('product'), row('sales_order'), row('purchase_order'),
      ]),
    ).toEqual([
      { entityType: 'sales_order', missing: [], inactive: [] },
      { entityType: 'purchase_order', missing: [], inactive: [] },
    ]);
  });

  it('computeDocumentPrerequisites - a disabled master counts as inactive', () => {
    expect(
      computeDocumentPrerequisites([
        row('customer', { enabled: false }), row('product', { etlStatus: 'paused' }), row('sales_order'),
      ]),
    ).toEqual([{ entityType: 'sales_order', missing: [], inactive: ['customer', 'product'] }]);
  });
});

describe('mock DB company - task connection lock (AC-01-09/10)', () => {
  beforeEach(() => resetEtlMockState());

  it('a DB company draft task defaults to the company connection', async () => {
    const created = await service.createCompany({ connectionId: 'conn-sql-2', name: '' });
    const task = await service.getEtlTask(created.id, 'customer');
    expect(task.sourceConfig.connectionId).toBe('conn-sql-2');
  });

  it('fills an omitted connectionId and refuses a different one on the field', async () => {
    const task = await service.getEtlTask('company-db', 'warehouse');
    const saved = await service.updateEtlTask('company-db', 'warehouse', {
      sourceConfig: { ...task.sourceConfig, connectionId: '', query: 'SELECT * FROM dbo.Location', keyColumns: ['Location'] },
    });
    expect(saved.sourceConfig.connectionId).toBe('conn-sql-1');
    const err = await rejected(
      service.updateEtlTask('company-db', 'warehouse', {
        sourceConfig: { ...task.sourceConfig, connectionId: 'conn-sql-2', query: 'SELECT * FROM dbo.Location' },
      }),
    );
    expect(err.status).toBe(422);
    expect(err.detail).toEqual({ fieldErrors: { connectionId: expect.any(String) } });
  });

  it('a saved query births the entity row sql_db - customer/supplier like the other seven', async () => {
    const task = await service.getEtlTask('company-db', 'supplier');
    await service.updateEtlTask('company-db', 'supplier', {
      sourceConfig: { ...task.sourceConfig, query: 'SELECT * FROM dbo.Creditor', keyColumns: ['AccNo'] },
    });
    const detail = await service.getCompany('company-db');
    const supplier = detail.entities.find((e) => e.entityType === 'supplier');
    expect(supplier?.sourceImpl).toBe('sql_db');
    // The purchase order's missing master is now merely inactive (draft).
    expect(detail.company.documentPrerequisites.find((p) => p.entityType === 'purchase_order')).toEqual({
      entityType: 'purchase_order', missing: [], inactive: ['supplier', 'product'],
    });
  });

  it('merely opening the task editor births nothing (no saved query = no row)', async () => {
    await service.getEtlTask('company-db', 'warehouse');
    const detail = await service.getCompany('company-db');
    expect(detail.entities.map((e) => e.entityType)).not.toContain('warehouse');
  });

  it('GRN is refused on a DB company (API-only envelope)', async () => {
    const task = await service.getEtlTask('company-db', 'goods_received_note');
    const err = await rejected(
      service.updateEtlTask('company-db', 'goods_received_note', {
        sourceConfig: { ...task.sourceConfig, query: 'SELECT * FROM dbo.GRN' },
      }),
    );
    expect(err.status).toBe(422);
  });

  it('an API company keeps the free picker - any connection saves (regression pin)', async () => {
    const task = await service.getEtlTask('company-1', 'warehouse');
    const saved = await service.updateEtlTask('company-1', 'warehouse', {
      sourceConfig: { ...task.sourceConfig, connectionId: 'conn-sql-2', query: 'SELECT * FROM dbo.Location' },
    });
    expect(saved.sourceConfig.connectionId).toBe('conn-sql-2');
  });
});
