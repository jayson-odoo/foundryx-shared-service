import { describe, expect, it } from 'vitest';
import {
  DEFAULT_STATUS_FORMULA,
  HTTP_PRESETS,
  LINE_AGGREGATES,
  REF_PREFIX_RE,
  STATUS_VOCABULARY,
  activatePrerequisites,
  anchorErrorTitle,
  brandContractBanner,
  derivePrefix,
  formatDurationMs,
  httpPreviewAsSqlPreview,
  httpPreviewBadgeText,
  incrementalFloorMinutes,
  isDocumentEntity,
  mappingSourceColumns,
  pickerColumnOptions,
  productDependencyWarning,
  readTaskError,
  previewBadgeText,
  previewFailedBlocksActivation,
  schemaCompletionConfig,
  starterQuery,
  statusFormulaSeed,
  todayDateString,
  validateIncrementalMinutes,
  validateReconcileAt,
  validateReconcileHours,
} from './autocount-etl';
import { evaluateFormula, validateFormula } from './autocount-formula';
import type { AutocountSqlPreview, AutocountSqlSchema, HttpPreview } from '@/types/autocount';

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


function task(
  over: Partial<import('@/types/autocount').AutocountEtlTask> = {},
): import('@/types/autocount').AutocountEtlTask {
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
      docDateColumn: null,
      filterFormula: null,
      incrementalMinutes: 5,
      reconcileMode: 'dailyAt' as const,
      reconcileHours: null,
      reconcileAt: '02:00',
    },
    resultColumns: ['AccNo', 'CompanyName'],
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
    sourceKind: 'api',
    documentPrerequisites: [],
    ...over,
  };
}

describe('activatePrerequisites (foolproof gate, AC-22-18)', () => {
  it('is clear for a saved sorento-bound task with a company code', () => {
    expect(activatePrerequisites({ company: company(), task: task(), configDirty: false })).toEqual([]);
  });

  it('is clear for a logging-sink company (a legitimate configured default, not an unfinished setup)', () => {
    const reasons = activatePrerequisites({
      company: company({ sinkImpl: 'logging', sinkConnectionId: null, sorentoCompanyCode: null }),
      task: task(),
      configDirty: false,
    });
    expect(reasons).toEqual([]);
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

  // sprint-5/08 fix (found via the agent-browser evidence run): an HTTP task
  // never has a `query`/`keyColumns` - the gate must check `path`/`keyFields`
  // for one, never the SQL-only fields unconditionally.
  it('an HTTP task with a saved path + key fields is clear, even though query/keyColumns are blank', () => {
    const httpTask = task({
      sourceImpl: 'autocount_http',
      sourceConfig: { ...task().sourceConfig, query: '', keyColumns: [], path: '/itembypage', keyFields: ['ItemCode'] },
    });
    expect(activatePrerequisites({ company: company(), task: httpTask, configDirty: false })).toEqual([]);
  });

  it('an HTTP task with no path yet reads "No endpoint saved yet."', () => {
    const httpTask = task({
      sourceImpl: 'autocount_http',
      sourceConfig: { ...task().sourceConfig, query: '', keyColumns: [], path: '', keyFields: [] },
    });
    const reasons = activatePrerequisites({ company: company(), task: httpTask, configDirty: false });
    expect(reasons).toEqual([{ kind: 'query', message: 'No endpoint saved yet.' }]);
  });

  it('an HTTP task with a path but no key fields reads "No key columns picked yet."', () => {
    const httpTask = task({
      sourceImpl: 'autocount_http',
      sourceConfig: { ...task().sourceConfig, query: '', keyColumns: [], path: '/itembypage', keyFields: [] },
    });
    const reasons = activatePrerequisites({ company: company(), task: httpTask, configDirty: false });
    expect(reasons).toEqual([{ kind: 'keys', message: 'No key columns picked yet.' }]);
  });
});

describe('previewFailedBlocksActivation (S5 review SHOULD-FIX 4b)', () => {
  it('blocks when the last preview reported failed rows', () => {
    expect(previewFailedBlocksActivation(task({ lastPreviewFailedCount: 2 }))).toBe(true);
  });

  it('never blocks on retryable-only (a legitimate dependency-order carry-over)', () => {
    expect(previewFailedBlocksActivation(task({ lastPreviewFailedCount: 0 }))).toBe(false);
    expect(previewFailedBlocksActivation(task({ lastPreviewFailedCount: null }))).toBe(false);
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

// ── plan 22 S5 review SHOULD-FIX 4c - status seed formula (a VALUE, not copy) ─

describe('statusFormulaSeed', () => {
  it('seeds the boolean-flag formula for status on a document entity + boolean column', () => {
    expect(statusFormulaSeed('sales_order', 'status', 'boolean')).toBe(
      'if(value == true, "cancelled", "open")',
    );
    expect(statusFormulaSeed('purchase_order', 'status', 'boolean')).toBe(
      'if(value == true, "cancelled", "open")',
    );
  });

  it('leaves it empty for a non-document entity', () => {
    expect(statusFormulaSeed('customer', 'status', 'boolean')).toBeNull();
  });

  it('leaves it empty for a field other than status', () => {
    expect(statusFormulaSeed('sales_order', 'so_number', 'boolean')).toBeNull();
  });

  it('leaves it empty when the source column is not boolean-typed', () => {
    expect(statusFormulaSeed('sales_order', 'status', 'string')).toBeNull();
    expect(statusFormulaSeed('sales_order', 'status', undefined)).toBeNull();
  });
});

// ── plan 22 S3 - schedule (AC-22-12..17) ─────────────────────────────────────

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

describe('productDependencyWarning (plan 22 S4, AC-22-23)', () => {
  it('is null for a non-product entity regardless of siblings', () => {
    expect(productDependencyWarning('customer', [])).toBeNull();
  });

  const WARNING = 'No active category or unit-of-measure task yet - products may not sync until one runs.';

  it('warns with the fixed copy when neither dependency is active', () => {
    expect(productDependencyWarning('product', [])).toBe(WARNING);
  });

  it('still warns when only ONE dependency lands (the copy names neither by design)', () => {
    const msg = productDependencyWarning('product', [
      { entityType: 'product_category', etlStatus: 'active' },
    ]);
    expect(msg).toBe(WARNING);
  });

  it('ignores a DRAFT/PAUSED sibling task - only ACTIVE resolves the dependency', () => {
    expect(
      productDependencyWarning('product', [
        { entityType: 'product_category', etlStatus: 'draft' },
        { entityType: 'unit_of_measure', etlStatus: 'paused' },
      ]),
    ).toBe(WARNING);
  });

  it('is null once both category and unit of measure are active', () => {
    expect(
      productDependencyWarning('product', [
        { entityType: 'product_category', etlStatus: 'active' },
        { entityType: 'unit_of_measure', etlStatus: 'active' },
      ]),
    ).toBeNull();
  });
});

describe('brandContractBanner (sprint-5/08, AC-08-33/AC-08-20 S5)', () => {
  it('names the real advertised version when the consumer does not yet accept brands', () => {
    expect(brandContractBanner({ brandContractGate: { version: 2.2, requiredVersion: 2.3 } })).toBe(
      'Consumer contract 2.2 - brands land when 2.3 is deployed',
    );
  });

  it('is null once the gate clears (contract 2.3 with brands advertised)', () => {
    expect(brandContractBanner({ brandContractGate: null })).toBeNull();
  });

  it('is null when the field is absent (every non-brand task, back-compat fixtures)', () => {
    expect(brandContractBanner({})).toBeNull();
  });
});

// ── sprint-5/02 - shipping_order is a document entity, line aggregates ──────

describe('isDocumentEntity - sprint-5/02', () => {
  it('treats shipping_order as a document entity', () => {
    expect(isDocumentEntity('shipping_order')).toBe(true);
  });
  it('still true for sales_order/purchase_order, false otherwise', () => {
    expect(isDocumentEntity('sales_order')).toBe(true);
    expect(isDocumentEntity('purchase_order')).toBe(true);
    expect(isDocumentEntity('customer')).toBe(false);
  });
});

describe('LINE_AGGREGATES / STATUS_VOCABULARY / DEFAULT_STATUS_FORMULA (AC-02-07/08/09)', () => {
  it('exposes exactly the five aggregate tokens', () => {
    expect(LINE_AGGREGATES.map((a) => a.token)).toEqual([
      'lines.count',
      'lines.open_count',
      'lines.ordered_sum',
      'lines.fulfilled_sum',
      'lines.outstanding_sum',
    ]);
  });
  it('the status vocabulary is the fixed 5-word set', () => {
    expect(STATUS_VOCABULARY).toEqual(['open', 'partial', 'fulfilled', 'closed', 'cancelled']);
  });
  it('the default status formula parses against its own variable set and never yields partial', () => {
    const knownVars = ['Cancelled', ...LINE_AGGREGATES.map((a) => a.token)];
    expect(validateFormula(DEFAULT_STATUS_FORMULA, knownVars)).toBeNull();
    expect(
      evaluateFormula(DEFAULT_STATUS_FORMULA, null, { Cancelled: 'T', 'lines.open_count': 3 }),
    ).toBe('cancelled');
    expect(
      evaluateFormula(DEFAULT_STATUS_FORMULA, null, { Cancelled: 'F', 'lines.open_count': 0 }),
    ).toBe('closed');
    expect(
      evaluateFormula(DEFAULT_STATUS_FORMULA, null, { Cancelled: 'F', 'lines.open_count': 2 }),
    ).toBe('open');
  });
});

// ── open REST API source (sprint-5/08, S1 frontend mock) ─────────────────────

describe('derivePrefix (AC-08-09)', () => {
  it('upper-cases and collapses non-alphanumerics to one underscore', () => {
    expect(derivePrefix('Mocha REST')).toBe('MOCHA_REST');
    expect(derivePrefix('Sorento - db2 (branch)')).toBe('SORENTO_DB2_BRANCH');
  });

  it('trims leading/trailing underscores', () => {
    expect(derivePrefix('  !!Mocha!!  ')).toBe('MOCHA');
  });
});

describe('REF_PREFIX_RE (AC-08-07)', () => {
  it('accepts the backend format and rejects anything shorter/foreign', () => {
    expect(REF_PREFIX_RE.test('MOCHA')).toBe(true);
    expect(REF_PREFIX_RE.test('MOCHA_2')).toBe(true);
    expect(REF_PREFIX_RE.test('M')).toBe(false);
    expect(REF_PREFIX_RE.test('mocha')).toBe(false);
    expect(REF_PREFIX_RE.test('MOCHA-2')).toBe(false);
    expect(REF_PREFIX_RE.test('')).toBe(false);
  });
});

describe('HTTP_PRESETS (AC-08-16)', () => {
  it('has exactly the six confirmed masters, each with a leading-slash path and key field(s)', () => {
    expect(Object.keys(HTTP_PRESETS)).toEqual([
      'product',
      'customer',
      'warehouse',
      'product_category',
      'brand',
      'unit_of_measure',
    ]);
    for (const preset of Object.values(HTTP_PRESETS)) {
      expect(preset.path.startsWith('/')).toBe(true);
      expect(preset.keyFields.length).toBeGreaterThan(0);
    }
  });

  it('unit_of_measure is derived from distinct UOM columns, keyed "value"', () => {
    expect(HTTP_PRESETS.unit_of_measure.distinctOf).toEqual(['BaseUOM', 'SalesUOM', 'PurchaseUOM']);
    expect(HTTP_PRESETS.unit_of_measure.keyFields).toEqual(['value']);
  });

  it('only product/customer carry a watermark (LastModified) - the four lookup lists have none', () => {
    expect(HTTP_PRESETS.product.watermarkField).toBe('LastModified');
    expect(HTTP_PRESETS.customer.watermarkField).toBe('LastModified');
    expect(HTTP_PRESETS.warehouse.watermarkField).toBeNull();
    expect(HTTP_PRESETS.product_category.watermarkField).toBeNull();
    expect(HTTP_PRESETS.brand.watermarkField).toBeNull();
    expect(HTTP_PRESETS.unit_of_measure.watermarkField).toBeNull();
  });
});

function httpPreview(over: Partial<HttpPreview> = {}): HttpPreview {
  return {
    envelope: 'paged',
    totalCount: 11826,
    columns: [{ name: 'ItemCode', sample: 'SRT-01' }],
    rows: [{ ItemCode: 'SRT-01' }],
    durationMs: 240,
    ...over,
  };
}

describe('httpPreviewBadgeText (D14 - the page walk is explicit)', () => {
  it('states the page count and that a run walks every page', () => {
    expect(httpPreviewBadgeText(httpPreview({ totalCount: 11826 }))).toBe(
      'Paged · 11,826 total · 12 pages of 1000 - a run walks every page',
    );
  });

  it('a list envelope states one request, no page math', () => {
    const rows = Array.from({ length: 60 }, (_, i) => ({ ItemGroup: `G${i}` }));
    expect(
      httpPreviewBadgeText(
        httpPreview({ envelope: 'list', totalCount: undefined, rows, columns: [{ name: 'ItemGroup', sample: 'G0' }] }),
      ),
    ).toBe('List · 60 rows · one request');
  });

  it('a single page still reads "1 page"', () => {
    expect(httpPreviewBadgeText(httpPreview({ totalCount: 60 }))).toBe(
      'Paged · 60 total · 1 page of 1000 - a run walks every page',
    );
  });
});

describe('httpPreviewAsSqlPreview (AC-08-19 - reuse SqlPreviewGrid, never a parallel grid)', () => {
  it('maps each column\'s sample value into the type slot and passes rows through', () => {
    const preview = httpPreview({
      columns: [
        { name: 'ItemCode', sample: 'SRT-01' },
        { name: 'IsActive', sample: null },
      ],
      rows: [{ ItemCode: 'SRT-01', IsActive: null }],
    });
    const adapted = httpPreviewAsSqlPreview(preview);
    expect(adapted.columns).toEqual([
      { name: 'ItemCode', type: 'SRT-01' },
      { name: 'IsActive', type: '' },
    ]);
    expect(adapted.rows).toBe(preview.rows);
    expect(adapted.rowCount).toBe(1);
    expect(adapted.truncated).toBe(false);
    expect(adapted.durationMs).toBe(240);
  });
});
