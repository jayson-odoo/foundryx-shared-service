import { describe, expect, it } from 'vitest';
import {
  activatePrerequisites,
  anchorErrorTitle,
  computeMockNextRunTimes,
  formatDurationMs,
  incrementalFloorMinutes,
  isDocumentEntity,
  mappingSourceColumns,
  pickerColumnOptions,
  readTaskError,
  previewBadgeText,
  schemaCompletionConfig,
  starterQuery,
  todayDateString,
  validateIncrementalMinutes,
  validateReconcileAt,
  validateReconcileHours,
} from './autocount-etl';
import type { AutocountEtlSourceConfig, AutocountSqlPreview, AutocountSqlSchema } from '@/types/autocount';

const SCHEMA: AutocountSqlSchema = {
  connectionId: 'conn-sql-1',
  dialect: 'mssql',
  database: 'AED',
  schemas: [
    {
      name: 'dbo',
      tables: [
        { name: 'Debtor', columns: [{ name: 'AccNo', type: 'varchar' }, { name: 'CompanyName', type: 'nvarchar' }] },
        { name: 'Stock', columns: [{ name: 'ItemCode', type: 'varchar' }] },
      ],
    },
    { name: 'audit', tables: [{ name: 'Log', columns: [{ name: 'Id', type: 'int' }] }] },
  ],
  introspectedAt: '2026-08-30T00:00:00Z',
};

function preview(overrides: Partial<AutocountSqlPreview> = {}): AutocountSqlPreview {
  return {
    columns: [{ name: 'AccNo', type: 'varchar' }],
    rows: [],
    rowCount: 0,
    truncated: false,
    durationMs: 310,
    ...overrides,
  };
}

describe('isDocumentEntity', () => {
  it('flags SO/PO only', () => {
    expect(isDocumentEntity('sales_order')).toBe(true);
    expect(isDocumentEntity('purchase_order')).toBe(true);
    expect(isDocumentEntity('customer')).toBe(false);
    expect(isDocumentEntity('supplier')).toBe(false);
  });
});

describe('pickerColumnOptions', () => {
  it('offers the preview columns first, then saved picks the preview lost', () => {
    expect(pickerColumnOptions(['AccNo', 'Name'], ['Name', 'Legacy'])).toEqual([
      'AccNo',
      'Name',
      'Legacy',
    ]);
  });

  it('is just the saved picks before any preview ran', () => {
    expect(pickerColumnOptions([], ['AccNo'])).toEqual(['AccNo']);
  });
});

describe('previewBadgeText', () => {
  it('states rows + duration, singular for one row', () => {
    expect(previewBadgeText(preview({ rowCount: 1 }))).toBe('1 row · 0.31 s');
    expect(previewBadgeText(preview({ rowCount: 12, durationMs: 1000 }))).toBe('12 rows · 1.00 s');
  });

  it('marks a capped result so 100 never reads as the whole set', () => {
    expect(previewBadgeText(preview({ rowCount: 100, truncated: true }))).toBe(
      '100 rows (first 100) · 0.31 s',
    );
  });
});

describe('schemaCompletionConfig', () => {
  it('keys tables by schema prefix and defaults to the first schema', () => {
    expect(schemaCompletionConfig(SCHEMA)).toEqual({
      schema: {
        'dbo.Debtor': ['AccNo', 'CompanyName'],
        'dbo.Stock': ['ItemCode'],
        'audit.Log': ['Id'],
      },
      defaultSchema: 'dbo',
    });
  });

  it('is empty without a schema', () => {
    expect(schemaCompletionConfig(null)).toEqual({ schema: {} });
  });
});

describe('starterQuery', () => {
  it('is the schema-qualified SELECT *', () => {
    expect(starterQuery('dbo', 'Debtor')).toBe('SELECT * FROM dbo.Debtor');
  });
});

describe('todayDateString', () => {
  it('is a YYYY-MM-DD date', () => {
    expect(todayDateString()).toMatch(/^\d{4}-\d{2}-\d{2}$/);
  });
});

// ── plan 22 S2 - activation gate, anchor errors, run cost (AC-22-17/18/19) ────


function task(over: Partial<import('@/types/autocount').AutocountEtlTask> = {}) {
  return {
    companyId: 'c1',
    entityType: 'customer',
    etlStatus: 'draft',
    activatedAt: null,
    sourceConfig: {
      connectionId: 'conn-sql-1',
      query: 'SELECT * FROM dbo.Debtor',
      lineQuery: null,
      keyColumns: ['AccNo'],
      watermarkColumn: null,
      comparedColumns: [],
      fromDate: null,
      incrementalMinutes: 5,
      reconcileMode: 'dailyAt' as const,
      reconcileHours: null,
      reconcileAt: '02:00',
    },
    resultColumns: ['AccNo', 'CompanyName'],
    lastPreviewAt: null,
    lastRunAt: null,
    lastRunError: null,
    lastRunErrorCode: null,
    nextIncrementalAt: null,
    nextReconcileAt: null,
    ...over,
  };
}

function company(over: Partial<import('@/types/autocount').AutocountCompany> = {}) {
  return {
    id: 'c1',
    connectionId: 'conn-1',
    databaseName: 'AED',
    companyName: 'AED',
    name: 'AED',
    isActive: true,
    sinkImpl: 'sorento',
    sinkConnectionId: 'conn-9',
    sorentoCompanyCode: 'SRT',
    createdAt: null,
    ...over,
  };
}

describe('activatePrerequisites (foolproof gate, AC-22-18)', () => {
  it('is clear for a saved sorento-bound task with a company code', () => {
    expect(activatePrerequisites({ company: company(), task: task(), configDirty: false })).toEqual([]);
  });

  it('withholds when the company delivers nowhere (logging sink)', () => {
    const reasons = activatePrerequisites({
      company: company({ sinkImpl: 'logging', sinkConnectionId: null, sorentoCompanyCode: null }),
      task: task(),
      configDirty: false,
    });
    expect(reasons.map((r) => r.kind)).toEqual(['sink']);
  });

  it('withholds when the Sorento company code is blank', () => {
    const reasons = activatePrerequisites({
      company: company({ sorentoCompanyCode: '  ' }),
      task: task(),
      configDirty: false,
    });
    expect(reasons.map((r) => r.kind)).toEqual(['companyCode']);
  });

  it('withholds on unsaved edits and on a task with no keys / no query', () => {
    expect(
      activatePrerequisites({ company: company(), task: task(), configDirty: true }).map((r) => r.kind),
    ).toEqual(['unsaved']);
    const noKeys = task();
    noKeys.sourceConfig.keyColumns = [];
    expect(
      activatePrerequisites({ company: company(), task: noKeys, configDirty: false }).map((r) => r.kind),
    ).toEqual(['keys']);
    const noQuery = task();
    noQuery.sourceConfig.query = '   ';
    expect(
      activatePrerequisites({ company: company(), task: noQuery, configDirty: false }).map((r) => r.kind),
    ).toEqual(['query']);
  });

  it('is unknown-company-safe: no company loaded = withheld, not clear', () => {
    expect(activatePrerequisites({ company: null, task: task(), configDirty: false }).length).toBe(1);
  });
});

describe('anchor errors (Appendix A6)', () => {
  it('titles every Sorento anchor code and falls back for the rest', () => {
    expect(anchorErrorTitle('COMPANY_ANCHOR_REQUIRED')).toBe('Sorento company code required');
    expect(anchorErrorTitle('UNKNOWN_COMPANY')).toBe('Unknown Sorento company');
    expect(anchorErrorTitle('COMPANY_ANCHOR_AMBIGUOUS')).toBe('Sorento company code is ambiguous');
    // S2 review SHOULD-FIX 8: the fourth Appendix A6 code (the integration's
    // OWN company binding is broken - a backend-side fault, not a save the
    // operator can fix by re-entering the company code) was missing from the
    // FE vocabulary and fell back to the generic "Task error" title.
    expect(anchorErrorTitle('COMPANY_BINDING_INVALID')).toBe('Sorento company binding is invalid');
    expect(anchorErrorTitle('SOMETHING_ELSE')).toBe('Task error');
    expect(anchorErrorTitle(null)).toBe('Task error');
  });

  it('reads the structured 422 detail and ignores anything else', () => {
    expect(readTaskError({ code: 'UNKNOWN_COMPANY', message: 'No company "ZZZ".' })).toEqual({
      code: 'UNKNOWN_COMPANY',
      message: 'No company "ZZZ".',
    });
    expect(readTaskError({ fieldErrors: { query: 'x' } })).toBeNull();
    expect(readTaskError('plain string')).toBeNull();
    expect(readTaskError(null)).toBeNull();
  });
});

describe('formatDurationMs', () => {
  it('renders sub-minute as seconds and longer as minutes', () => {
    expect(formatDurationMs(400)).toBe('0.4 s');
    expect(formatDurationMs(6100)).toBe('6.1 s');
    expect(formatDurationMs(125000)).toBe('2 min 5 s');
    expect(formatDurationMs(null)).toBe('-');
  });
});

describe('mappingSourceColumns (AC-22-09 source picker)', () => {
  it('unions the saved result columns, the live preview and the rows already mapped', () => {
    expect(
      mappingSourceColumns(['AccNo', 'CompanyName'], ['AccNo', 'Phone1'], ['CompanyName', 'Legacy']),
    ).toEqual(['AccNo', 'CompanyName', 'Phone1', 'Legacy']);
  });

  it('is empty when nothing is known yet', () => {
    expect(mappingSourceColumns([], [], [])).toEqual([]);
  });
});

// ── plan 22 S3 - schedule (AC-22-12..17) ─────────────────────────────────────

function sourceConfig(over: Partial<AutocountEtlSourceConfig> = {}): AutocountEtlSourceConfig {
  return {
    connectionId: 'conn-sql-1',
    query: 'SELECT * FROM dbo.Debtor',
    lineQuery: null,
    keyColumns: ['AccNo'],
    watermarkColumn: null,
    comparedColumns: [],
    fromDate: null,
    incrementalMinutes: 15,
    reconcileMode: 'dailyAt',
    reconcileHours: null,
    reconcileAt: '02:00',
    ...over,
  };
}

describe('incrementalFloorMinutes (AC-22-12)', () => {
  it('is 1 minute with a watermark column, 15 without', () => {
    expect(incrementalFloorMinutes(true)).toBe(1);
    expect(incrementalFloorMinutes(false)).toBe(15);
  });
});

describe('validateIncrementalMinutes (AC-22-12)', () => {
  it('accepts at the floor and above', () => {
    expect(validateIncrementalMinutes(1, true)).toBeNull();
    expect(validateIncrementalMinutes(15, false)).toBeNull();
    expect(validateIncrementalMinutes(60, false)).toBeNull();
  });

  it('rejects below the watermark-driven floor', () => {
    expect(validateIncrementalMinutes(0, true)).toMatch(/at least 1 minute/i);
    expect(validateIncrementalMinutes(5, false)).toMatch(/at least 15 minutes/i);
  });

  it('rejects a blank/non-finite value', () => {
    expect(validateIncrementalMinutes(null, true)).toMatch(/enter the incremental interval/i);
    expect(validateIncrementalMinutes(NaN, true)).toMatch(/enter the incremental interval/i);
  });
});

describe('validateReconcileHours (AC-22-12)', () => {
  it('accepts >= 1 hour, rejects below and blank', () => {
    expect(validateReconcileHours(1)).toBeNull();
    expect(validateReconcileHours(24)).toBeNull();
    expect(validateReconcileHours(0)).toMatch(/at least 1 hour/i);
    expect(validateReconcileHours(null)).toMatch(/enter the reconcile interval/i);
  });
});

describe('validateReconcileAt (AC-22-12)', () => {
  it('accepts a valid HH:MM, rejects everything else', () => {
    expect(validateReconcileAt('02:00')).toBeNull();
    expect(validateReconcileAt('23:59')).toBeNull();
    expect(validateReconcileAt('24:00')).toMatch(/HH:MM/);
    expect(validateReconcileAt('9:00')).toMatch(/HH:MM/);
    expect(validateReconcileAt('')).toMatch(/HH:MM/);
    expect(validateReconcileAt(null)).toMatch(/HH:MM/);
  });
});

describe('computeMockNextRunTimes (plan 22 S3, PHASE 1 MOCK)', () => {
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
