/**
 * AutoCount ESB mock service (hop 2, plan 14 phase 4) - frontend-first
 * scaffolding behind the service boundary. The real backend is live, so the
 * shipped `autocountService` binds `.real`; this mock exists so the dry-run
 * review states (previewable / not-previewable / failure) are tunable with NO
 * backend, and so the Vitest suite can drive them deterministically.
 *
 * PHASE 1 MOCK - do NOT let a component import this directly. It lives behind
 * `autocount-service.ts`; flip that one line to `mockAutocountService` to build
 * the UI against it, and back to `.real` to ship.
 *
 * Preview state is selected from the `jobId` so every state is reachable
 * without a backend:
 *   - `*logging*` / `*nopreview*`  → not previewable (logging sink)
 *   - `*fail*`                     → the dry run failed (throws HTTP 502)
 *   - anything else                → a realistic previewable payload
 *
 * PHASE 1 MOCK (plan sprint-5/01 S1) - DB-only company onboarding is built
 * against this mock FIRST; the S2 backend swaps it out. The contract it
 * encodes lives in the "DB-only company fixtures" section below.
 */
import { ApiError } from '@/lib/api-client';
import { testFormula as evalFormula } from '@/lib/autocount-formula';
import {
  DEFAULT_STATUS_FORMULA,
  HTTP_PRESETS,
  MIN_RECONCILE_HOURS,
  REF_PREFIX_RE,
  RECONCILE_TIME_RE,
  incrementalFloorMinutes,
  isDocumentEntity,
} from '@/lib/autocount-etl';
import type {
  AutocountApiConnection,
  AutocountApprovalResult,
  AutocountCompany,
  AutocountCompanyCreateInput,
  AutocountCompanyDetail,
  AutocountDocumentPrerequisite,
  AutocountEntityConfig,
  AutocountEntityConfigUpdate,
  AutocountEtlPreviewResult,
  AutocountEtlRunStart,
  AutocountEtlSourceConfig,
  AutocountEtlTask,
  AutocountEtlTaskUpdate,
  AutocountPreview,
  AutocountFormulaTestResult,
  AutocountJobListQuery,
  AutocountMappingPreset,
  AutocountMappingUpdate,
  AutocountMappingView,
  AutocountMappingWriteRow,
  AutocountPreviewResult,
  AutocountSimulateFieldResult,
  AutocountSimulateResult,
  AutocountSinkTargetInput,
  AutocountSorentoField,
  AutocountSourceImpl,
  AutocountSqlConnection,
  AutocountSqlPreview,
  AutocountSqlSchema,
  AutocountSqlTable,
  AutocountStagedList,
  AutocountStagedQuery,
  AutocountStagedRecord,
  AutocountSyncJob,
  AutocountSyncJobBatch,
  AutocountSyncRun,
  HttpPreview,
  HttpPreviewInput,
} from '@/types/autocount';
import type { ListResult } from '@/types/resource';
import type { AutocountListQuery, AutocountService } from './autocount-service';

function mockCompany(overrides: Partial<AutocountCompany> = {}): AutocountCompany {
  return {
    id: 'company-1',
    connectionId: 'conn-autocount-1',
    databaseName: 'AED_VSOFT',
    companyName: 'AED VSoft Sdn Bhd',
    name: 'AED VSoft',
    isActive: true,
    sinkImpl: 'logging',
    sinkConnectionId: null,
    sorentoCompanyCode: null,
    createdAt: '2026-07-01T00:00:00Z',
    sourceKind: 'api',
    documentPrerequisites: [],
    ...overrides,
  };
}

function previewablePayload(jobId: string): AutocountPreviewResult {
  return { jobId, preview: previewableBlock() };
}

/** The realistic previewable dry-run block (batch review AND the S2 task gate). */
function previewableBlock(): AutocountPreview {
  return {
      previewable: true,
      sink: 'sorento',
      summary: { total: 172, created: 134, updated: 38, failed: 0, retryable: 0 },
      predictions: [
        // An adoption that BLANKS a live value + overwrites a name - the
        // destructive rows an operator most needs to see.
        {
          sourceRef: 'AED_VSOFT:3',
          outcome: 'updated',
          entityId: 'sup-3',
          changesLiveData: true,
          diff: {
            payment_terms_days: { current: 30, incoming: null },
            customer_name: { current: 'ONE STOP HOME DESIGN', incoming: 'OW PIN BOON' },
          },
          errors: {},
        },
        {
          sourceRef: 'AED_VSOFT:7',
          outcome: 'updated',
          entityId: 'sup-7',
          changesLiveData: true,
          diff: {
            email: { current: 'old@acme.test', incoming: 'billing@acme.test' },
          },
          errors: {},
        },
        // A create - no diff, safe, summarised.
        {
          sourceRef: 'AED_VSOFT:50',
          outcome: 'created',
          entityId: null,
          changesLiveData: false,
          diff: {},
          errors: {},
        },
        {
          sourceRef: 'AED_VSOFT:51',
          outcome: 'created',
          entityId: null,
          changesLiveData: false,
          diff: {},
          errors: {},
        },
      ],
  };
}

function mockName(record: AutocountStagedRecord): string {
  const name = record.canonical?.name;
  return typeof name === 'string' ? name : '';
}

/**
 * A batch with BOTH kinds of staged row - a handful the operator must see
 * (field changes / a failure) and a wall of no-field-change re-fetches - so the
 * paginate + no-change-collapse behaviour (AC-15-10/11) is reachable with no
 * backend.
 */
function mockStagedRecords(): AutocountStagedRecord[] {
  const changed: AutocountStagedRecord[] = [
    {
      id: 'staged-3',
      entityType: 'supplier',
      sourceRef: 'AED_VSOFT:3',
      docNo: '400-J001',
      status: 'STAGED',
      diff: { name: { from: 'ONE STOP HOME DESIGN', to: 'OW PIN BOON' } },
      canonical: { code: '400-J001', name: 'OW PIN BOON', is_active: true },
      errors: null,
      error: null,
      hasChanges: true,
      sourceLastModified: '2026-03-18T08:03:21Z',
    },
    {
      id: 'staged-7',
      entityType: 'supplier',
      sourceRef: 'AED_VSOFT:7',
      docNo: '400-J007',
      status: 'STAGED',
      diff: { email: { from: 'old@acme.test', to: 'billing@acme.test' } },
      canonical: { code: '400-J007', name: 'ACME TRADING', is_active: true },
      errors: null,
      error: null,
      hasChanges: true,
      sourceLastModified: '2026-03-19T02:11:00Z',
    },
    {
      id: 'staged-9',
      entityType: 'supplier',
      sourceRef: 'AED_VSOFT:9',
      docNo: '400-J009',
      status: 'FAILED',
      diff: null,
      canonical: { code: '400-J009', name: 'NO CODE SUPPLIER' },
      errors: [{ field: 'code', message: 'Required field is empty.' }],
      error: null,
      hasChanges: true,
      sourceLastModified: '2026-03-19T04:00:00Z',
    },
  ];
  // 24 legitimate no-op re-fetches - LastModified advanced, no mapped field
  // differs. These must collapse, never bury the three above.
  const noChange: AutocountStagedRecord[] = Array.from({ length: 24 }, (_, i) => ({
    id: `staged-nc-${i}`,
    entityType: 'supplier',
    sourceRef: `AED_VSOFT:${100 + i}`,
    docNo: `400-N${String(i).padStart(3, '0')}`,
    status: 'STAGED' as const,
    diff: {},
    canonical: { code: `400-N${String(i).padStart(3, '0')}`, name: `SUPPLIER ${i}` },
    errors: null,
    error: null,
    hasChanges: false,
    sourceLastModified: '2026-03-20T00:00:00Z',
  }));
  return [...changed, ...noChange];
}

// ── direct-DB ETL fixtures (plan 22 S1 - PHASE 1 MOCK is the backend spec) ───

/** Small pause so loading states are real (visible spinners, no flash). */
function pause(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

/** Detach a stored fixture from what the caller mutates. */
function cloneJson<T>(value: T): T {
  return JSON.parse(JSON.stringify(value)) as T;
}

/**
 * The tenant's `sql_database` connections. A healthy MSSQL source (bound to
 * the seeded DB company below), a second healthy one a DB company can be
 * CREATED from, one whose database is already an API company's (the 409 path),
 * and a PostgreSQL one whose every connect FAILS - so the editor's connection-
 * error state AND the create form's 422 are reachable by a real click, no
 * backend needed.
 */
const SQL_CONNECTIONS: AutocountSqlConnection[] = [
  {
    id: 'conn-sql-1',
    name: 'AutoCount SQL Server',
    dialect: 'mssql',
    database: 'AED_Sorento_2024',
  },
  {
    id: 'conn-sql-2',
    name: 'AutoCount SQL Server (branch)',
    dialect: 'mssql',
    database: 'AED_BRANCH',
  },
  {
    id: 'conn-sql-vsoft',
    name: 'AutoCount SQL Server (VSoft)',
    dialect: 'mssql',
    database: 'AED_VSOFT',
  },
  {
    id: 'conn-sql-down',
    name: 'Reporting PostgreSQL',
    dialect: 'postgresql',
    database: 'reporting',
  },
];

/** AutoCount-shaped table catalog (name → columns) - the schema tree, the
 * editor autocomplete and the preview generator all read from this one map. */
const SQL_TABLES: AutocountSqlTable[] = [
  {
    name: 'Debtor',
    columns: [
      { name: 'AccNo', type: 'varchar(12)' },
      { name: 'CompanyName', type: 'nvarchar(100)' },
      { name: 'Phone1', type: 'nvarchar(25)' },
      { name: 'EmailAddress', type: 'nvarchar(60)' },
      { name: 'IsActive', type: 'char(1)' },
      { name: 'LastModified', type: 'datetime' },
    ],
  },
  {
    name: 'Creditor',
    columns: [
      { name: 'AccNo', type: 'varchar(12)' },
      { name: 'CompanyName', type: 'nvarchar(100)' },
      { name: 'Phone1', type: 'nvarchar(25)' },
      { name: 'EmailAddress', type: 'nvarchar(60)' },
      { name: 'IsActive', type: 'char(1)' },
      { name: 'LastModified', type: 'datetime' },
    ],
  },
  {
    name: 'Stock',
    columns: [
      { name: 'ItemCode', type: 'varchar(30)' },
      { name: 'Description', type: 'nvarchar(100)' },
      { name: 'ItemGroup', type: 'varchar(12)' },
      { name: 'BaseUOM', type: 'varchar(10)' },
      { name: 'IsActive', type: 'char(1)' },
      { name: 'LastModified', type: 'datetime' },
    ],
  },
  {
    name: 'StockGroup',
    columns: [
      { name: 'ItemGroup', type: 'varchar(12)' },
      { name: 'Description', type: 'nvarchar(60)' },
      { name: 'IsActive', type: 'char(1)' },
    ],
  },
  {
    name: 'ItemUOM',
    columns: [
      { name: 'ItemCode', type: 'varchar(30)' },
      { name: 'UOM', type: 'varchar(10)' },
      { name: 'Rate', type: 'decimal(18,6)' },
    ],
  },
  {
    // Zero rows on purpose - the preview's EMPTY state by a real click.
    name: 'Location',
    columns: [
      { name: 'Location', type: 'varchar(12)' },
      { name: 'Description', type: 'nvarchar(60)' },
      { name: 'IsActive', type: 'char(1)' },
    ],
  },
  {
    name: 'SalesAgent',
    columns: [
      { name: 'SalesAgent', type: 'varchar(12)' },
      { name: 'Description', type: 'nvarchar(60)' },
      { name: 'IsActive', type: 'char(1)' },
    ],
  },
  {
    name: 'SO',
    columns: [
      { name: 'DocKey', type: 'bigint' },
      { name: 'DocNo', type: 'varchar(20)' },
      { name: 'DebtorCode', type: 'varchar(12)' },
      { name: 'Agent', type: 'varchar(12)' },
      { name: 'DocDate', type: 'datetime' },
      { name: 'Cancelled', type: 'char(1)' },
      { name: 'LastModified', type: 'datetime' },
    ],
  },
  {
    name: 'SODtl',
    columns: [
      { name: 'DtlKey', type: 'bigint' },
      { name: 'DocKey', type: 'bigint' },
      { name: 'ItemCode', type: 'varchar(30)' },
      { name: 'Qty', type: 'decimal(18,4)' },
      { name: 'UnitPrice', type: 'decimal(18,4)' },
      { name: 'Location', type: 'varchar(12)' },
    ],
  },
  {
    name: 'PO',
    columns: [
      { name: 'DocKey', type: 'bigint' },
      { name: 'DocNo', type: 'varchar(20)' },
      { name: 'CreditorCode', type: 'varchar(12)' },
      { name: 'DocDate', type: 'datetime' },
      { name: 'Cancelled', type: 'char(1)' },
      { name: 'LastModified', type: 'datetime' },
    ],
  },
  {
    name: 'PODtl',
    columns: [
      { name: 'DtlKey', type: 'bigint' },
      { name: 'DocKey', type: 'bigint' },
      { name: 'ItemCode', type: 'varchar(30)' },
      { name: 'Qty', type: 'decimal(18,4)' },
      { name: 'UnitPrice', type: 'decimal(18,4)' },
    ],
  },
];

/** How many source rows each table "has" (>100 exercises the cap indicator). */
const SQL_TABLE_ROWS: Record<string, number> = {
  Debtor: 172,
  Creditor: 12,
  Stock: 486,
  StockGroup: 6,
  ItemUOM: 4,
  Location: 0,
  SalesAgent: 5,
  SO: 31,
  SODtl: 118,
  PO: 9,
  PODtl: 27,
};

function mockSqlSchema(connection: AutocountSqlConnection): AutocountSqlSchema {
  return {
    connectionId: connection.id,
    dialect: connection.dialect,
    database: connection.database,
    schemas: [{ name: 'dbo', tables: SQL_TABLES }],
    introspectedAt: '2026-08-30T06:00:00Z',
  };
}

/** Deterministic sample value per column (name-driven, stable per row). */
function sampleValue(column: string, type: string, row: number): unknown {
  const names = [
    'Aneka Elektrik Deras',
    'Bintang Cool Air Sdn Bhd',
    'Ceria Aircond Services',
    'Delima Hardware Trading',
    'Emas Jaya Enterprise',
  ];
  if (/char|text/i.test(type)) {
    if (column === 'AccNo') return `3000/${String.fromCharCode(65 + (row % 26))}${String(row).padStart(2, '0')}`;
    if (column === 'CompanyName' || column === 'Description') return names[row % names.length];
    if (column === 'Phone1') return `03-55${String(1000 + row).slice(1)} ${String(2200 + row).slice(1)}`;
    if (column === 'EmailAddress') return row % 7 === 3 ? null : `acc${row}@example.my`;
    if (column === 'IsActive' || column === 'Cancelled') return row % 9 === 5 ? 'F' : 'T';
    if (column === 'ItemCode') return `ITM-${String(row).padStart(4, '0')}`;
    if (column === 'ItemGroup') return ['AIRCOND', 'PARTS', 'SERVICE'][row % 3];
    if (column === 'BaseUOM' || column === 'UOM') return ['UNIT', 'BOX', 'SET'][row % 3];
    if (column === 'Location') return ['HQ', 'PENANG'][row % 2];
    if (column === 'SalesAgent') return `AG${String(1 + (row % 5)).padStart(2, '0')}`;
    if (column === 'DocNo') return `SO-${String(2600 + row)}`;
    if (column === 'DebtorCode' || column === 'CreditorCode') return `3000/A${String(row % 20).padStart(2, '0')}`;
    if (column === 'Agent') return `AG${String(1 + (row % 5)).padStart(2, '0')}`;
    return `Value ${row}`;
  }
  if (/bigint|int/i.test(type)) return 1000 + row;
  if (/decimal|numeric|float/i.test(type)) return Number((row * 12.5 + 9.9).toFixed(2));
  if (/date|time/i.test(type)) {
    const day = String(1 + (row % 28)).padStart(2, '0');
    return `2026-08-${day} ${String(8 + (row % 10)).padStart(2, '0')}:14:0${row % 10}`;
  }
  return null;
}

/**
 * The mock's stand-in for the server-side SELECT-only guard + preview run.
 * Mirrors the real behaviour classes exactly: 422 before the source for a
 * non-SELECT, 400 sanitized for a bad object, capped rows for a big table.
 */
function runMockPreview(query: string): AutocountSqlPreview {
  const text = query.trim().replace(/;\s*$/, '');
  if (!text) {
    throw new ApiError('Only a single SELECT statement can be previewed.', 422);
  }
  const first = text.split(/\s+/, 1)[0]?.toUpperCase();
  if ((first !== 'SELECT' && first !== 'WITH') || text.includes(';')) {
    throw new ApiError('Only a single SELECT statement can be previewed.', 422);
  }
  const match = /\bFROM\s+(?:\[?dbo\]?\.)?\[?(\w+)\]?/i.exec(text);
  const tableName = match?.[1];
  const table = SQL_TABLES.find(
    (t) => t.name.toLowerCase() === tableName?.toLowerCase(),
  );
  if (!table) {
    // The sanitized shape of a real driver error - no DSN, no stack.
    throw new ApiError(`Invalid object name '${tableName ?? '?'}'.`, 400);
  }
  const total = SQL_TABLE_ROWS[table.name] ?? 0;
  const rowCount = Math.min(total, 100);
  const rows = Array.from({ length: rowCount }, (_, i) => {
    const record: Record<string, unknown> = {};
    for (const col of table.columns) {
      record[col.name] = sampleValue(col.name, col.type, i);
    }
    return record;
  });
  return {
    columns: table.columns.map((c) => ({ name: c.name, type: c.type })),
    rows,
    rowCount,
    truncated: total > 100,
    durationMs: 180 + rowCount * 3,
  };
}

/**
 * Draft defaults for a never-configured entity (documents get a from-date).
 * `connectionId` is genuinely OPTIONAL (`null` = "nothing picked yet") - a
 * SQL connection default here was a latent bug (sprint-5/08 fix): a
 * non-`db` company's blank task silently inherited an ARBITRARY SQL
 * connection id, which `baseline`'s `saved.connectionId ?? lockId` then
 * treated as "already picked", so an http/api company's lock never actually
 * reached `config.connectionId` (the locked DISPLAY read the lock directly
 * and looked correct; Test/Save silently used the wrong connection).
 */
function defaultEtlConfig(
  entityType: string,
  connectionId: string | null = null,
): AutocountEtlSourceConfig {
  return {
    connectionId,
    query: '',
    lineQuery: isDocumentEntity(entityType) ? '' : null,
    keyColumns: [],
    watermarkColumn: null,
    comparedColumns: [],
    fromDate: isDocumentEntity(entityType) ? '2026-08-30' : null,
    docDateColumn: null,
    filterFormula: null,
    incrementalMinutes: 5,
    reconcileMode: 'dailyAt',
    reconcileHours: null,
    reconcileAt: '02:00',
  };
}

/** In-memory task store so draft saves round-trip within the session. */
const etlTasks = new Map<string, AutocountEtlTask>();

/** A never-configured entity's DRAFT task. On a DB company the draft's
 * connection is the company connection (the server fills it, AC-01-09). */
function blankTask(companyId: string, entityType: string): AutocountEtlTask {
  const company = mockCompanyState(companyId);
  return {
    companyId,
    entityType,
    etlStatus: 'draft',
    activatedAt: null,
    sourceConfig: defaultEtlConfig(
      entityType,
      company.sourceKind === 'db' ? company.connectionId : null,
    ),
    resultColumns: [],
    lastPreviewAt: null,
    lastPreviewFailedCount: null,
    lastRunAt: null,
    lastRunError: null,
    lastRunErrorCode: null,
    nextIncrementalAt: null,
    nextReconcileAt: null,
  };
}

function etlTaskFor(companyId: string, entityType: string): AutocountEtlTask {
  if (companyId === DB_COMPANY_ID) ensureDbCompanySeed();
  const key = `${companyId}:${entityType}`;
  const existing = etlTasks.get(key);
  if (existing) return existing;
  const task = blankTask(companyId, entityType);
  etlTasks.set(key, task);
  return task;
}

// ── plan 22 S2 fixtures (PHASE 1 MOCK is the backend spec) ───────────────────
//
// Every S2 state is reachable by a real click, selected from data the operator
// already controls:
//   company delivery `logging`            → preview "nothing to preview"
//   sorento + blank company code          → preview 422 COMPANY_ANCHOR_REQUIRED
//   sorento + code `UNKNOWN`              → preview 422 UNKNOWN_COMPANY
//   sorento + code starting `AMBIG`       → preview 422 COMPANY_ANCHOR_AMBIGUOUS
//   sorento + code `DOWN`                 → preview 502 (consumer unreachable)
//   sorento + any other code              → previewable payload → Activate
//   Run now after changing the code to `UNKNOWN` → a FAILED run + task-level
//   `lastRunError` (the anchor error on a scheduled run, never per record).

/** What ONE session's task lifecycle stores beyond the S1 draft config. */
interface EtlTaskOverlay {
  etlStatus: AutocountEtlTask['etlStatus'];
  activatedAt: string | null;
  resultColumns: string[];
  lastPreviewAt: string | null;
  lastPreviewFailedCount: number | null;
  lastRunAt: string | null;
  lastRunError: string | null;
  lastRunErrorCode: string | null;
}

const etlOverlays = new Map<string, EtlTaskOverlay>();
const companyCodes = new Map<string, string | null>();
/** Pure-mock only: the persisted sink target per company (the overlay reads
 * the REAL company's sink instead). */
const mockSinks = new Map<string, Pick<AutocountCompany, 'sinkImpl' | 'sinkConnectionId'>>();
const sourceImpls = new Map<string, AutocountSourceImpl>();
/** Result columns of every preview run this session, by normalized query. */
const previewColumnsByQuery = new Map<string, string[]>();
const etlRuns = new Map<string, AutocountSyncRun[]>();
/**
 * Test seam (plan sprint-5/07, AC-07-20) - the ONLY way to reach the "a run
 * is in flight" 409 with no backend: set a run id here and the next
 * `repushEtlTask` call throws it instead of clearing anything. Cleared by
 * `resetEtlMockState`.
 */
let mockRepushInFlightRunId: string | null = null;

export function setMockRepushInFlight(runId: string | null): void {
  mockRepushInFlightRunId = runId;
}

function taskKey(companyId: string, entityType: string): string {
  return `${companyId}:${entityType}`;
}

function normalizeQuery(query: string): string {
  return query.trim().replace(/\s+/g, ' ').replace(/;$/, '').toLowerCase();
}

function nowIso(): string {
  return new Date().toISOString();
}

function overlayFor(companyId: string, entityType: string): EtlTaskOverlay {
  const key = taskKey(companyId, entityType);
  const existing = etlOverlays.get(key);
  if (existing) return existing;
  const fresh: EtlTaskOverlay = {
    etlStatus: 'draft',
    activatedAt: null,
    resultColumns: [],
    lastPreviewAt: null,
    lastPreviewFailedCount: null,
    lastRunAt: null,
    lastRunError: null,
    lastRunErrorCode: null,
  };
  etlOverlays.set(key, fresh);
  return fresh;
}

/**
 * Mirrors `EtlService.next_run_times` exactly - minutes floor by watermark
 * presence for the incremental leg; `interval` mode = now + N hours;
 * `dailyAt` = the next occurrence of HH:MM, treated as UTC (there is no
 * tenant-level timezone setting to re-resolve against - only a per-user
 * preference, which has no natural owner for an unattended scheduled task;
 * BL-SS-034 tracks adding one). Mock-only + test-only: the real backend now
 * puts `nextIncrementalAt`/`nextReconcileAt` on the wire (plan 22 S3), so
 * this stands in only for `mockAutocountService`.
 */
export function computeMockNextRunTimes(
  sourceConfig: AutocountEtlSourceConfig,
  now: Date = new Date(),
): { nextIncrementalAt: string; nextReconcileAt: string } {
  const floor = incrementalFloorMinutes(Boolean(sourceConfig.watermarkColumn));
  const minutes = Math.max(sourceConfig.incrementalMinutes || 0, floor);
  const nextIncrementalAt = new Date(now.getTime() + minutes * 60_000).toISOString();

  let nextReconcileAt: string;
  if (sourceConfig.reconcileMode === 'interval') {
    const hours = Math.max(sourceConfig.reconcileHours ?? MIN_RECONCILE_HOURS, MIN_RECONCILE_HOURS);
    nextReconcileAt = new Date(now.getTime() + hours * 3_600_000).toISOString();
  } else {
    const at =
      sourceConfig.reconcileAt && RECONCILE_TIME_RE.test(sourceConfig.reconcileAt)
        ? sourceConfig.reconcileAt
        : '02:00';
    const [hour, minute] = at.split(':').map(Number);
    const target = new Date(now);
    target.setUTCHours(hour, minute, 0, 0);
    if (target.getTime() <= now.getTime()) target.setUTCDate(target.getUTCDate() + 1);
    nextReconcileAt = target.toISOString();
  }
  return { nextIncrementalAt, nextReconcileAt };
}

/**
 * The next-run pair a task carries while active (plan 22 S3, PHASE 1 MOCK -
 * `computeMockNextRunTimes` above stands in for the not-yet-wired backend
 * fields). Null the instant the task is not active - a paused or draft task
 * shows no next runs.
 */
function nextRunsFor(etlStatus: AutocountEtlTask['etlStatus'], sourceConfig: AutocountEtlSourceConfig) {
  if (etlStatus !== 'active') return { nextIncrementalAt: null, nextReconcileAt: null };
  return computeMockNextRunTimes(sourceConfig);
}

/**
 * AC-08-33/AC-08-20 S5 - the Review & Activate banner's mock source of
 * truth: a `brand` task on a Sorento-sink company reads GATED (contract 2.2)
 * by default, the SAME real-world state the backend probe reports today.
 * The operator flips it OPEN by setting the Sorento company code to
 * `BRANDS23` (2.3, the consumer now advertises brands) - the SAME
 * "pick a company-code sentinel" convention `anchorError`/the `DOWN` code
 * already use above, never a hidden toggle with no on-screen control.
 */
function brandContractGateFor(task: AutocountEtlTask): AutocountEtlTask['brandContractGate'] {
  if (task.entityType !== 'brand') return null;
  const company = applyCompanyOverlay(mockCompanyState(task.companyId));
  if (company.sinkImpl !== 'sorento') return null;
  if ((company.sorentoCompanyCode ?? '').trim().toUpperCase() === 'BRANDS23') return null;
  return { version: 2.2, requiredVersion: 2.3 };
}

/** Lay the session's lifecycle state over a (real or mock) task. */
function applyTaskOverlay(task: AutocountEtlTask): AutocountEtlTask {
  const o = overlayFor(task.companyId, task.entityType);
  const impl = sourceImpls.get(taskKey(task.companyId, task.entityType));
  return {
    ...task,
    ...o,
    sourceConfig: task.sourceConfig,
    // sprint-5/08 D13 - present on every task (defaults 'sql_db'); an
    // entity-level 'autocount_read' override never touches the TASK's own
    // impl (there is no task on that path at all).
    sourceImpl: impl === 'autocount_http' ? 'autocount_http' : 'sql_db',
    brandContractGate: brandContractGateFor(task),
    ...nextRunsFor(o.etlStatus, task.sourceConfig),
  };
}

/** `httpPreview` result columns this session, by (connection, path, distinctOf). */
const httpPreviewColumnsByKey = new Map<string, string[]>();

function httpPreviewKey(connectionId: string, path: string, distinctOf?: string[] | null): string {
  return `${connectionId}|${path}|${(distinctOf ?? []).join(',')}`;
}

/** The columns a saved query/endpoint yields - from the session's preview of
 * it, else the saved picks (so an existing task still lists something to
 * map). `impl` selects the SQL-query cache or the HTTP-path cache - the two
 * never collide on the same task (sprint-5/08). */
function resultColumnsFor(
  cfg: AutocountEtlSourceConfig,
  impl: 'sql_db' | 'autocount_http' = 'sql_db',
): string[] {
  if (impl === 'autocount_http') {
    const seen = httpPreviewColumnsByKey.get(
      httpPreviewKey(cfg.connectionId ?? '', cfg.path ?? '', cfg.distinctOf),
    );
    if (seen) return [...seen];
    const picks = [
      ...(cfg.keyFields ?? []),
      ...(cfg.watermarkField ? [cfg.watermarkField] : []),
      ...(cfg.comparedFields ?? []),
    ];
    return Array.from(new Set(picks));
  }
  const seen = previewColumnsByQuery.get(normalizeQuery(cfg.query));
  if (seen) return [...seen];
  const picks = [...cfg.keyColumns, ...(cfg.watermarkColumn ? [cfg.watermarkColumn] : []), ...cfg.comparedColumns];
  return Array.from(new Set(picks));
}

/**
 * A config save supersedes any earlier preview (the gate must re-run,
 * AC-22-11/AC-08-13). `implOrSourceChanged` (AC-08-28) additionally drops an
 * ACTIVE task back to `draft` when the impl, connection or (HTTP) path just
 * changed - never on an unrelated field edit.
 */
function noteTaskSaved(
  companyId: string,
  entityType: string,
  cfg: AutocountEtlSourceConfig,
  impl: 'sql_db' | 'autocount_http' = 'sql_db',
  implOrSourceChanged = false,
): void {
  const o = overlayFor(companyId, entityType);
  o.resultColumns = resultColumnsFor(cfg, impl);
  o.lastPreviewAt = null;
  o.lastPreviewFailedCount = null;
  if (implOrSourceChanged && o.etlStatus === 'active') o.etlStatus = 'draft';
}

/**
 * The pure mock's company: a `*legacy*` id models a row that delivered to
 * Sorento BEFORE the company code existed (backfilled NULL) - the only way a
 * sorento sink with a blank code can exist, since the save guard refuses it.
 */
function mockCompanyState(id: string): AutocountCompany {
  const legacy = id.includes('legacy');
  const sink = mockSinks.get(id);
  const created = createdCompanies.get(id);
  const createdOpen = createdOpenCompanies.get(id);
  let base: AutocountCompany;
  if (id === DB_COMPANY_ID) base = mockDbCompany();
  else if (id === HTTP_COMPANY_ID) base = mockHttpCompany();
  else if (createdOpen) base = { ...createdOpen };
  else if (created) base = { ...created };
  else {
    base = mockCompany({
      id,
      sinkImpl: legacy ? 'sorento' : 'logging',
      sinkConnectionId: legacy ? 'conn-9' : null,
    });
  }
  return sink ? { ...base, sinkImpl: sink.sinkImpl, sinkConnectionId: sink.sinkConnectionId } : base;
}

function applyCompanyOverlay(company: AutocountCompany): AutocountCompany {
  return {
    ...company,
    sorentoCompanyCode: companyCodes.has(company.id)
      ? companyCodes.get(company.id) ?? null
      : company.sorentoCompanyCode ?? null,
  };
}

function applyEntityOverlay(companyId: string, entity: AutocountEntityConfig): AutocountEntityConfig {
  const impl = sourceImpls.get(taskKey(companyId, entity.entityType));
  return impl ? { ...entity, sourceImpl: impl } : entity;
}

function applyDetailOverlay(detail: AutocountCompanyDetail): AutocountCompanyDetail {
  return {
    company: applyCompanyOverlay(detail.company),
    entities: detail.entities.map((e) => applyEntityOverlay(detail.company.id, e)),
  };
}

/** The sink-target save-time guard the backend must mirror (Appendix A6). */
function guardSinkTarget(input: AutocountSinkTargetInput): void {
  if (input.sinkImpl !== 'sorento') return;
  if (!input.sinkConnectionId) {
    throw new ApiError('Choose a Sorento connection.', 422, null, {
      fieldErrors: { sinkConnectionId: 'Choose a Sorento connection.' },
    });
  }
  if (!(input.sorentoCompanyCode ?? '').trim()) {
    throw new ApiError('Sorento company code is required.', 422, null, {
      fieldErrors: { sorentoCompanyCode: 'Sorento company code is required.' },
    });
  }
}

function noteSinkTarget(companyId: string, input: AutocountSinkTargetInput): void {
  companyCodes.set(
    companyId,
    input.sinkImpl === 'sorento' ? (input.sorentoCompanyCode ?? '').trim() : null,
  );
}

/** Switching source: never discards the query; an active task is paused. */
function noteSourceImpl(companyId: string, entityType: string, impl: AutocountSourceImpl): void {
  sourceImpls.set(taskKey(companyId, entityType), impl);
  if (impl === 'autocount_read') {
    const o = overlayFor(companyId, entityType);
    if (o.etlStatus === 'active') o.etlStatus = 'paused';
  }
}

/** The anchor verdict Sorento would return for a company code (A6 codes). */
function anchorError(code: string | null): { code: string; message: string } | null {
  const c = (code ?? '').trim();
  if (!c) {
    return {
      code: 'COMPANY_ANCHOR_REQUIRED',
      message: 'A company anchor is required: set the Sorento company code on this company.',
    };
  }
  if (c.toUpperCase() === 'UNKNOWN') {
    return { code: 'UNKNOWN_COMPANY', message: `No Sorento company matches code '${c}'.` };
  }
  if (c.toUpperCase().startsWith('AMBIG')) {
    return {
      code: 'COMPANY_ANCHOR_AMBIGUOUS',
      message: `Code '${c}' matches more than one Sorento company.`,
    };
  }
  return null;
}

/** The mock's dry-run: the same behaviour classes the real endpoint must reproduce. */
async function mockPreviewEtlTask(
  company: AutocountCompany,
  task: AutocountEtlTask,
): Promise<AutocountEtlPreviewResult> {
  await pause(350);
  const impl = sourceImpls.get(taskKey(task.companyId, task.entityType));
  const configured =
    impl === 'autocount_http'
      ? Boolean(task.sourceConfig.path?.trim()) && (task.sourceConfig.keyFields?.length ?? 0) > 0
      : Boolean(task.sourceConfig.query.trim()) && task.sourceConfig.keyColumns.length > 0;
  if (!configured) {
    throw new ApiError('Save a query with key columns before previewing.', 409);
  }
  const o = overlayFor(task.companyId, task.entityType);
  if (company.sinkImpl !== 'sorento') {
    return {
      task: applyTaskOverlay(task),
      preview: {
        previewable: false,
        sink: 'logging',
        reason: 'No consumer is configured for this company, so there is nothing to preview.',
      },
    };
  }
  const anchor = anchorError(company.sorentoCompanyCode);
  if (anchor) {
    throw new ApiError(anchor.message, 422, null, anchor);
  }
  if ((company.sorentoCompanyCode ?? '').trim().toUpperCase() === 'DOWN') {
    throw new ApiError(
      'The dry run against the consumer failed. Nothing was written - resolve the consumer error first.',
      502,
    );
  }
  o.lastPreviewAt = nowIso();
  // The mock never models a genuinely-failed prediction (only the anchor/
  // consumer-down error classes above) - 0, never left null, so the
  // activation gate (S5 review SHOULD-FIX 4b) reads a completed preview
  // that reported nothing to fix.
  o.lastPreviewFailedCount = 0;
  return { task: applyTaskOverlay(task), preview: previewableBlock() };
}

function mockRun(over: Partial<AutocountSyncRun> & { id: string; entityType: string }): AutocountSyncRun {
  return {
    jobId: `job-${over.id}`,
    windowFrom: null,
    windowTo: null,
    fetchedCount: 0,
    stagedCount: 0,
    failedCount: 0,
    pushedCount: 0,
    outcome: 'SUCCESS',
    error: null,
    truncated: false,
    watermarkAdvancedTo: null,
    startedAt: '2026-08-30T06:32:00Z',
    finishedAt: '2026-08-30T06:32:00Z',
    mode: 'incremental',
    rowsScanned: 0,
    addedCount: 0,
    updatedCount: 0,
    deletedCount: 0,
    durationMs: 200,
    skipReason: null,
    ...over,
  };
}

/** The realistic history an activated task accrues (mockup §06): a delivered
 * incremental, a no-change tick, an overlap-skipped tick, a reconcile with a
 * delete, a delete-guard fail-safe, and the initial manual load. Newest first. */
function seedRunHistory(companyId: string, entityType: string, activatedAt: string): void {
  const base = Date.parse(activatedAt);
  const at = (offsetMs: number) => new Date(base + offsetMs).toISOString();
  const rows: AutocountSyncRun[] = [
    mockRun({
      id: `${entityType}-r6`, entityType, mode: 'incremental', rowsScanned: 2, updatedCount: 2,
      fetchedCount: 2, stagedCount: 2, pushedCount: 2, durationMs: 400,
      startedAt: at(5 * 60_000), finishedAt: at(5 * 60_000 + 400),
    }),
    mockRun({
      id: `${entityType}-r5`, entityType, mode: 'incremental', durationMs: 200,
      startedAt: at(4 * 60_000), finishedAt: at(4 * 60_000 + 200),
    }),
    mockRun({
      id: `${entityType}-r4`, entityType, mode: 'skipped', jobId: null, outcome: 'SKIPPED',
      durationMs: null, skipReason: 'The previous run was still executing.',
      startedAt: at(3 * 60_000), finishedAt: at(3 * 60_000),
    }),
    mockRun({
      id: `${entityType}-r3`, entityType, mode: 'reconcile', rowsScanned: 172, addedCount: 1,
      updatedCount: 3, deletedCount: 1, fetchedCount: 172, stagedCount: 5, pushedCount: 5,
      durationMs: 6100, startedAt: at(2 * 60_000), finishedAt: at(2 * 60_000 + 6100),
    }),
    mockRun({
      id: `${entityType}-r2`, entityType, mode: 'reconcile', rowsScanned: 171, deletedCount: 38,
      fetchedCount: 171, outcome: 'FAILED', durationMs: 1900,
      error: 'Delete guard: 38 delete intents exceed 20% of 172 known rows. Nothing was pushed.',
      startedAt: at(60_000), finishedAt: at(60_000 + 1900),
    }),
    mockRun({
      id: `${entityType}-r1`, entityType, mode: 'manual', rowsScanned: 172, addedCount: 134,
      updatedCount: 38, fetchedCount: 172, stagedCount: 172, pushedCount: 172, durationMs: 8200,
      startedAt: at(0), finishedAt: at(8200),
    }),
  ];
  etlRuns.set(taskKey(companyId, entityType), rows);
}

function mockActivate(company: AutocountCompany, task: AutocountEtlTask): AutocountEtlTask {
  const o = overlayFor(task.companyId, task.entityType);
  if (o.etlStatus === 'active') throw new ApiError('This task is already active.', 409);
  if (!o.lastPreviewAt) {
    throw new ApiError('Run a successful preview before activating.', 409);
  }
  if (company.sinkImpl !== 'sorento' || !(company.sorentoCompanyCode ?? '').trim()) {
    throw new ApiError('Set a Sorento company code on the company before activating.', 409);
  }
  const wasPaused = o.etlStatus === 'paused';
  o.etlStatus = 'active';
  o.activatedAt = nowIso();
  if (!wasPaused) seedRunHistory(task.companyId, task.entityType, o.activatedAt);
  return applyTaskOverlay(task);
}

function mockPause(task: AutocountEtlTask): AutocountEtlTask {
  const o = overlayFor(task.companyId, task.entityType);
  if (o.etlStatus !== 'active') throw new ApiError('Only an active task can be paused.', 409);
  o.etlStatus = 'paused';
  return applyTaskOverlay(task);
}

function mockResume(task: AutocountEtlTask): AutocountEtlTask {
  const o = overlayFor(task.companyId, task.entityType);
  if (o.etlStatus !== 'paused') throw new ApiError('Only a paused task can be resumed.', 409);
  o.etlStatus = 'active';
  return applyTaskOverlay(task);
}

function mockRunNow(company: AutocountCompany, task: AutocountEtlTask): AutocountEtlRunStart {
  const o = overlayFor(task.companyId, task.entityType);
  if (o.etlStatus !== 'active') throw new ApiError('Only an active task can be run.', 409);
  const key = taskKey(task.companyId, task.entityType);
  const history = etlRuns.get(key) ?? [];
  const id = `${task.entityType}-m${history.length + 1}`;
  const started = nowIso();
  const anchor = anchorError(company.sorentoCompanyCode);
  const run = anchor
    ? mockRun({
        id, entityType: task.entityType, mode: 'manual', rowsScanned: 172, fetchedCount: 172,
        stagedCount: 172, outcome: 'FAILED', error: `${anchor.code}: ${anchor.message}`,
        durationMs: 900, startedAt: started, finishedAt: started,
      })
    : mockRun({
        id, entityType: task.entityType, mode: 'manual', rowsScanned: 172, updatedCount: 3,
        fetchedCount: 172, stagedCount: 3, pushedCount: 3, durationMs: 1400,
        startedAt: started, finishedAt: started,
      });
  etlRuns.set(key, [run, ...history]);
  o.lastRunAt = started;
  o.lastRunError = anchor ? anchor.message : null;
  o.lastRunErrorCode = anchor ? anchor.code : null;
  return { runId: run.id, jobId: run.jobId ?? `job-${run.id}`, status: 'done', task: applyTaskOverlay(task) };
}

function mockListEtlRuns(
  companyId: string,
  entityType: string,
  query: AutocountListQuery = {},
): ListResult<AutocountSyncRun> {
  const all = etlRuns.get(taskKey(companyId, entityType)) ?? [];
  const page = query.page ?? 0;
  const pageSize = query.pageSize ?? 25;
  return {
    data: all.slice(page * pageSize, page * pageSize + pageSize).map((r) => ({ ...r })),
    total: all.length,
    page,
  };
}

// ── DB-only company fixtures (plan sprint-5/01 S1 - PHASE 1 MOCK is the backend spec) ──
//
// BACKEND CONTRACT (S2 must match this EXACTLY - the hook + views are built on it):
//
//   POST /autocount/companies {connectionId, name?}   (gated autocount.companies.manage)
//     connection provider `autocount`    → the existing API flow, unchanged (AC-01-01).
//     connection provider `sql_database` → a DB company (AC-01-01..06): database_name =
//       config.database (trimmed) verified by the dialect's live current-database probe;
//       company_name best-effort from `dbo.Profile` (blank on any failure, never an
//       error); NO ac_entity_config / ac_field_mapping seeds; activity `discover company`.
//       409 when the connection is already bound OR the database already has a company
//           of EITHER kind: "'<database>' is already connected as company '<label>'."
//       422 {fieldErrors: {connectionId}} on a probe mismatch ("This login lands on
//           '<probe>', but the connection names '<config>'.") or a connect/auth failure
//           (the SANITIZED runtime message - never credentials, never a DSN).
//     any other provider, or another tenant's connection → uniform 404
//           "That connection was not found."
//
//   GET /autocount/companies · GET /autocount/companies/{id}     (AC-01-07, AC-01-11)
//     CompanyItem += `sourceKind: 'api' | 'db'` - DERIVED from the connection's provider
//       (the list resolves connections in ONE batched tenant-scoped query; a deleted
//       connection reports 'api' and never 500s) and `documentPrerequisites:
//       [{entityType, missing[], inactive[]}]` for each configured document entity
//       (`sales_order` needs customer+product, `purchase_order` supplier+product;
//       missing = no config row, inactive = row with etl_status != 'active' or disabled).
//       The detail populates it; the LIST returns [].
//
//   PUT .../entities/{entityType}/etl-task · POST .../etl-task/preview on a DB company
//     an OMITTED source_config.connectionId is FILLED with company.connection_id; a
//       DIFFERENT one is 422 {fieldErrors: {connectionId: "A database company reads only
//       from its own connection."}} (AC-01-09). API companies keep the free picker.
//     the first save for `customer` / `supplier` births the row `sql_db` like the other
//       seven (AC-01-10); `goods_received_note` is 422 "not available on a database
//       company".
//
//   PATCH .../entities/{entityType} {sourceImpl: 'autocount_read'} and every vendor-client
//     path on a DB company → 409/422 "This company is connected by database; the AutoCount
//     API is not available." (AC-01-08) - never ConnectionNotFound, never a 500.
//
// Click-reachable states (no backend):
//   conn-sql-1      bound to the seeded, in-use DB company `company-db` (excluded from the
//                   create picker - offering it would guarantee the 409)
//   conn-sql-2      unbound + healthy → Create succeeds → the new company's Overview
//   conn-sql-vsoft  unbound, database AED_VSOFT = the API company's → 409 inline
//   conn-sql-down   unbound + unreachable → 422 on connectionId inline
//   company-db      Entities: customer + sales_order ACTIVE, product + purchase_order DRAFT,
//                   no supplier → the prerequisite card shows one inactive-only line and
//                   one missing+inactive line; a freshly created DB company has no entities
//                   (AC-01-05) → no card, Add entity offers all nine.

// ── open REST API source fixtures (sprint-5/08, S1 - PHASE 1 MOCK is the backend spec) ──
//
// BACKEND CONTRACT (S2/S3 must match this EXACTLY - the mock IS the spec).
// See the full contract block atop `autocount-service.ts`.
//
// Click-reachable states (no backend):
//   conn-api-sorento  open (no-auth), unbound → the Sorento DB company's
//                     Source-tab API branch can point HTTP tasks at it
//                     (AC-08-36); also pickable on the connect form.
//   conn-api-mocha    open (no-auth), bound to the seeded `company-http`
//                     (Mocha) - excluded from the connect picker.
//   conn-api-vendor   basic-auth, unbound - the "Basic auth" badge + the
//                     ref-prefix field NOT shown when picked.
//   /itembypage       paged, 11,826 total (12 pages of 1000) - `product`.
//   /debtorbypage     paged, 4,224 total (5 pages of 1000) - `customer`.
//   /location         list, 2 rows - `warehouse` (small on purpose).
//   /ItemGroup        list, 60 rows - `product_category`.
//   /ItemBrand        list, 12 rows - `brand`.
//   /itembypage + distinctOf ["BaseUOM","SalesUOM","PurchaseUOM"] - `unit_of_measure`.
//   /bogus            422 on `path` ("Not found").
//   any connectionId not in HTTP_API_CONNECTIONS, or a basic-auth one → 422 on `connectionId`.

const HTTP_API_CONNECTIONS: AutocountApiConnection[] = [
  {
    id: 'conn-api-sorento',
    name: 'Sorento REST',
    baseUrl: 'https://hapi.sorento.cc.cd/api/db1',
    auth: 'none',
  },
  {
    id: 'conn-api-mocha',
    name: 'Mocha REST',
    baseUrl: 'https://hapi.sorento.cc.cd/api/db2',
    auth: 'none',
  },
  {
    id: 'conn-api-vendor',
    name: 'AutoCount Vendor API',
    baseUrl: 'https://api.autocountcloud.com',
    auth: 'basic',
  },
];

function httpConnectionFor(id: string): AutocountApiConnection | undefined {
  return HTTP_API_CONNECTIONS.find((c) => c.id === id);
}

function isoStamp(daysAgo: number): string {
  return new Date(Date.now() - daysAgo * 86_400_000).toISOString().replace(/\.\d+Z$/, '');
}

const ITEM_GROUPS = ['AIRCOND', 'PARTS', 'SERVICE', 'HARDWARE', 'ELECTRICAL'];
const ITEM_BRANDS = ['DAIKIN', 'PANASONIC', 'MITSUBISHI', 'YORK', 'CARRIER', 'LG'];
const UOMS = ['UNIT', 'BOX', 'SET', 'PCS'];

/** ~30 realistic `/itembypage` rows - the `product` preset's preview sample. */
function itemRows(count = 30): Array<Record<string, unknown>> {
  return Array.from({ length: count }, (_, i) => ({
    ItemCode: `SRT-${String(i + 1).padStart(3, '0')}`,
    Description: `Item ${i + 1}`,
    Desc2: i % 4 === 0 ? '' : `Variant ${i}`,
    ItemGroup: ITEM_GROUPS[i % ITEM_GROUPS.length],
    ItemBrand: ITEM_BRANDS[i % ITEM_BRANDS.length],
    BaseUOM: UOMS[i % UOMS.length],
    SalesUOM: UOMS[(i + 1) % UOMS.length],
    PurchaseUOM: UOMS[(i + 2) % UOMS.length],
    LastModified: isoStamp(i),
    IsActive: i % 11 === 5 ? 'F' : 'T',
    Discontinued: i % 17 === 3 ? 'T' : 'F',
  }));
}

function debtorRows(count = 30): Array<Record<string, unknown>> {
  return Array.from({ length: count }, (_, i) => ({
    AccNo: `300-${String(i + 1).padStart(4, '0')}`,
    CompanyName: `Customer ${i + 1} Sdn Bhd`,
    Phone1: `03-77${String(1000 + i).slice(1)}`,
    IsActive: i % 13 === 6 ? 'F' : 'T',
    LastModified: isoStamp(i),
  }));
}

const LOCATION_ROWS: Array<Record<string, unknown>> = [
  { Location: 'HQ', Description: 'Head Office', Address1: 'Jalan Utama', IsActive: 'T' },
  { Location: 'PENANG', Description: 'Penang Branch', Address1: 'Jalan Timah', IsActive: 'T' },
];

const ITEM_GROUP_ROWS: Array<Record<string, unknown>> = Array.from({ length: 60 }, (_, i) => ({
  ItemGroup: `GRP${String(i + 1).padStart(2, '0')}`,
  Description: `${ITEM_GROUPS[i % ITEM_GROUPS.length]} ${Math.floor(i / ITEM_GROUPS.length) + 1}`,
}));

const ITEM_BRAND_ROWS: Array<Record<string, unknown>> = ITEM_BRANDS.map((b) => ({
  ItemBrand: b,
  Description: '',
}));

/** One path's full fixture: envelope shape + the rows behind it. */
interface HttpPathFixture {
  envelope: 'paged' | 'list';
  totalCount?: number;
  rows: Array<Record<string, unknown>>;
}

const HTTP_PATH_FIXTURES: Record<string, HttpPathFixture> = {
  '/itembypage': { envelope: 'paged', totalCount: 11826, rows: itemRows() },
  '/debtorbypage': { envelope: 'paged', totalCount: 4224, rows: debtorRows() },
  '/location': { envelope: 'list', rows: LOCATION_ROWS },
  '/ItemGroup': { envelope: 'list', rows: ITEM_GROUP_ROWS },
  '/ItemBrand': { envelope: 'list', rows: ITEM_BRAND_ROWS },
};

/** Distinct, trimmed, non-blank, first-seen-order projection (mirrors the
 * backend's `distinctOf` extraction, AC-08-22). */
function distinctValues(rows: Array<Record<string, unknown>>, fields: string[]): string[] {
  const seen = new Set<string>();
  const out: string[] = [];
  for (const row of rows) {
    for (const field of fields) {
      const raw = row[field];
      const value = typeof raw === 'string' ? raw.trim() : raw == null ? '' : String(raw);
      if (!value || seen.has(value)) continue;
      seen.add(value);
      out.push(value);
    }
  }
  return out;
}

/** The mock's `POST /autocount/http/preview` - the behaviour classes the
 * real endpoint must reproduce (AC-08-14). */
async function mockPreviewHttp(input: HttpPreviewInput): Promise<HttpPreview> {
  await pause(600);
  const connection = httpConnectionFor(input.connectionId);
  if (!connection || connection.auth !== 'none') {
    throw new ApiError('Choose an open (no-auth) AutoCount connection.', 422, null, {
      fieldErrors: { connectionId: 'Choose an open (no-auth) AutoCount connection.' },
    });
  }
  const path = input.path.trim();
  if (!path.startsWith('/') || path.includes('..') || path.includes('?')) {
    throw new ApiError('Enter a valid endpoint path.', 422, null, {
      fieldErrors: { path: 'Enter a valid endpoint path.' },
    });
  }
  const fixture = HTTP_PATH_FIXTURES[path];
  if (!fixture) {
    throw new ApiError(`'${path}' was not found.`, 422, null, {
      fieldErrors: { path: `'${path}' was not found.` },
    });
  }
  const rows50 = fixture.rows.slice(0, 50);
  if (input.distinctOf && input.distinctOf.length > 0) {
    const values = distinctValues(fixture.rows, input.distinctOf).slice(0, 50);
    return {
      envelope: fixture.envelope,
      totalCount: fixture.envelope === 'paged' ? fixture.totalCount : undefined,
      columns: [{ name: 'value', sample: values[0] ?? null }],
      rows: values.map((value) => ({ value })),
      durationMs: 180,
    };
  }
  const columnNames = Object.keys(rows50[0] ?? {});
  return {
    envelope: fixture.envelope,
    totalCount: fixture.envelope === 'paged' ? fixture.totalCount : undefined,
    columns: columnNames.map((name) => ({ name, sample: rows50[0]?.[name] ?? null })),
    rows: rows50,
    durationMs: 220,
  };
}

/** The seeded open (Mocha) company - no database at all (D3/D4). */
const HTTP_COMPANY_ID = 'company-http';
const HTTP_COMPANY_CONNECTION = HTTP_API_CONNECTIONS[1]; // Mocha REST

function mockHttpCompany(): AutocountCompany {
  return mockCompany({
    id: HTTP_COMPANY_ID,
    connectionId: HTTP_COMPANY_CONNECTION.id,
    databaseName: 'MOCHA',
    companyName: 'Mocha Sdn Bhd',
    name: 'Mocha',
    sourceKind: 'http',
    createdAt: '2026-09-10T00:00:00Z',
  });
}

/** Open companies registered this session (created from a No-auth connection). */
const createdOpenCompanies = new Map<string, AutocountCompany>();

const DB_COMPANY_ID = 'company-db';
const DB_COMPANY_CONNECTION = SQL_CONNECTIONS[0];

/** The seeded DB company - in use for a while, so its Entities tab has state. */
function mockDbCompany(): AutocountCompany {
  return mockCompany({
    id: DB_COMPANY_ID,
    connectionId: DB_COMPANY_CONNECTION.id,
    databaseName: DB_COMPANY_CONNECTION.database,
    companyName: 'Sorento Trading Sdn Bhd',
    name: 'Sorento Trading',
    sourceKind: 'db',
    createdAt: '2026-08-30T00:00:00Z',
  });
}

/** DB companies registered this session (created from a `sql_database` connection). */
const createdCompanies = new Map<string, AutocountCompany>();

/** Best-effort `dbo.Profile` company names per connection (absent = unreadable → blank). */
const PROFILE_NAMES: Record<string, string> = {
  'conn-sql-2': 'Sorento Trading (Branch) Sdn Bhd',
};

/** Mirrors the backend's DOCUMENT_PREREQUISITES (plan §2.2). */
const DOCUMENT_PREREQUISITES: Record<string, string[]> = {
  sales_order: ['customer', 'product'],
  purchase_order: ['supplier', 'product'],
  shipping_order: ['supplier', 'product', 'warehouse'],
};

/** Display order of a DB company's rows - the ten `sql_db` entities in dependency order. */
const DB_ENTITY_ORDER = [
  'customer',
  'supplier',
  'product_category',
  'unit_of_measure',
  'warehouse',
  'product',
  'sales_agent',
  'sales_order',
  'purchase_order',
  'shipping_order',
];

/** The pure function the backend's `document_prerequisites(company)` must mirror. */
export function computeDocumentPrerequisites(
  entities: AutocountEntityConfig[],
): AutocountDocumentPrerequisite[] {
  const byType = new Map(entities.map((e) => [e.entityType, e]));
  return entities
    .filter((e) => e.entityType in DOCUMENT_PREREQUISITES)
    .map((doc) => {
      const masters = DOCUMENT_PREREQUISITES[doc.entityType];
      return {
        entityType: doc.entityType,
        missing: masters.filter((m) => !byType.has(m)),
        inactive: masters.filter((m) => {
          const row = byType.get(m);
          return row !== undefined && (row.etlStatus !== 'active' || !row.enabled);
        }),
      };
    });
}

/** The in-use DB company's saved tasks: two active, two still draft. */
const DB_SEED_TASKS: {
  entityType: string;
  status: EtlTaskOverlay['etlStatus'];
  config: Partial<AutocountEtlSourceConfig>;
}[] = [
  {
    entityType: 'customer',
    status: 'active',
    config: {
      query: 'SELECT AccNo, CompanyName, Phone1, EmailAddress, IsActive, LastModified FROM dbo.Debtor',
      keyColumns: ['AccNo'],
      watermarkColumn: 'LastModified',
    },
  },
  {
    entityType: 'product',
    status: 'draft',
    config: {
      query: 'SELECT ItemCode, Description, ItemGroup, BaseUOM, IsActive, LastModified FROM dbo.Stock',
      keyColumns: ['ItemCode'],
      watermarkColumn: 'LastModified',
    },
  },
  {
    entityType: 'sales_order',
    status: 'active',
    config: {
      query: 'SELECT DocKey, DocNo, DebtorCode, Agent, DocDate, Cancelled, LastModified FROM dbo.SO',
      lineQuery:
        'SELECT DtlKey, DocKey, ItemCode, Qty, UnitPrice, Location FROM dbo.SODtl WHERE DocKey = :doc_key',
      keyColumns: ['DocKey'],
      watermarkColumn: 'LastModified',
      fromDate: '2026-01-01',
      docDateColumn: 'DocDate',
    },
  },
  {
    entityType: 'purchase_order',
    status: 'draft',
    config: {
      query: 'SELECT DocKey, DocNo, CreditorCode, DocDate, Cancelled, LastModified FROM dbo.PO',
      lineQuery: 'SELECT DtlKey, DocKey, ItemCode, Qty, UnitPrice FROM dbo.PODtl WHERE DocKey = :doc_key',
      keyColumns: ['DocKey'],
      watermarkColumn: 'LastModified',
      fromDate: '2026-01-01',
      docDateColumn: 'DocDate',
    },
  },
];

let dbSeeded = false;

/** Lazily materialize the seeded DB company's tasks (re-applied after a reset). */
function ensureDbCompanySeed(): void {
  if (dbSeeded) return;
  dbSeeded = true;
  for (const seed of DB_SEED_TASKS) {
    const key = taskKey(DB_COMPANY_ID, seed.entityType);
    if (!etlTasks.has(key)) {
      etlTasks.set(key, {
        ...blankTask(DB_COMPANY_ID, seed.entityType),
        sourceConfig: {
          ...defaultEtlConfig(seed.entityType, DB_COMPANY_CONNECTION.id),
          ...seed.config,
        },
      });
    }
    const o = overlayFor(DB_COMPANY_ID, seed.entityType);
    o.etlStatus = seed.status;
    o.resultColumns = resultColumnsFor(etlTasks.get(key)!.sourceConfig);
    if (seed.status === 'active') {
      o.activatedAt = '2026-08-30T06:00:00Z';
      o.lastPreviewAt = '2026-08-30T05:55:00Z';
      o.lastPreviewFailedCount = 0;
    }
  }
}

/** The API company's seeded rows (`SEEDED_ENTITIES` - the plan-13 path, unchanged). */
function apiSeedEntities(companyId: string): AutocountEntityConfig[] {
  return [
    {
      id: `${companyId}-customer`,
      entityType: 'customer',
      syncMode: 'SCHEDULED_REVIEW',
      sourceImpl: 'autocount_read',
      recordCap: 200,
      initialLookbackDays: 30,
      enabled: true,
      lastSuccessAt: null,
      lastAttemptAt: null,
      watermarkAt: null,
      consecutiveFailures: 0,
      lastError: null,
      etlStatus: 'draft',
    },
  ];
}

/**
 * Rows born on the DB source: a task exists AND has a SAVED query (opening the
 * editor alone births nothing - `update_task` "a row that exists ONLY for the
 * DB path is born on the DB source", plan 22 S4).
 */
function bornEntities(companyId: string): AutocountEntityConfig[] {
  const rows: AutocountEntityConfig[] = [];
  for (const [key, task] of Array.from(etlTasks.entries())) {
    if (!key.startsWith(`${companyId}:`)) continue;
    // A row is born the moment EITHER task grammar has a saved source
    // (sprint-5/08 D13 - an `autocount_http` task never has a `query`, only
    // `path`; the SQL branch is unaffected, still gated on `query`).
    const configured = task.sourceConfig.query.trim() || task.sourceConfig.path?.trim();
    if (!configured) continue;
    const o = overlayFor(companyId, task.entityType);
    const impl = sourceImpls.get(key) === 'autocount_http' ? 'autocount_http' : 'sql_db';
    rows.push({
      id: `${companyId}-${task.entityType}`,
      entityType: task.entityType,
      syncMode: 'AUTO',
      sourceImpl: impl,
      recordCap: 200,
      initialLookbackDays: 30,
      enabled: true,
      lastSuccessAt: o.lastRunAt && !o.lastRunError ? o.lastRunAt : null,
      lastAttemptAt: o.lastRunAt,
      watermarkAt: null,
      consecutiveFailures: o.lastRunError ? 1 : 0,
      lastError: o.lastRunError,
      etlStatus: o.etlStatus,
    });
  }
  const order = (t: string) => {
    const i = DB_ENTITY_ORDER.indexOf(t);
    return i === -1 ? DB_ENTITY_ORDER.length : i;
  };
  return rows.sort((a, b) => order(a.entityType) - order(b.entityType));
}

/** A company's entity rows: API seeds (API company only, AC-01-05) + born DB rows.
 * An open (http) company seeds nothing either - D13 mirrors the DB branch. */
function companyEntities(company: AutocountCompany): AutocountEntityConfig[] {
  if (company.id === DB_COMPANY_ID) ensureDbCompanySeed();
  const base =
    company.sourceKind === 'db' || company.sourceKind === 'http'
      ? []
      : apiSeedEntities(company.id);
  const seen = new Set(base.map((e) => e.entityType));
  return [...base, ...bornEntities(company.id).filter((e) => !seen.has(e.entityType))];
}

/** Every company the tenant holds: the API one, the seeded DB one, the seeded
 * open (Mocha) one, the session's creates of either kind. */
function allCompanies(): AutocountCompany[] {
  return [
    mockCompanyState('company-1'),
    mockCompanyState(DB_COMPANY_ID),
    mockCompanyState(HTTP_COMPANY_ID),
    ...Array.from(createdCompanies.keys()).map(mockCompanyState),
    ...Array.from(createdOpenCompanies.keys()).map(mockCompanyState),
  ].map(applyCompanyOverlay);
}

/** The create dispatcher the backend's `CompanyService.create` must mirror
 * (sprint-5/08 D1/D6 adds the THIRD branch: an open/no-auth `autocount`
 * connection). */
async function mockCreateCompany(input: AutocountCompanyCreateInput): Promise<AutocountCompany> {
  await pause(300);
  const sql = SQL_CONNECTIONS.find((c) => c.id === input.connectionId);
  const openApi = httpConnectionFor(input.connectionId);
  if (openApi?.auth === 'none') {
    return mockCreateOpenCompany(input, openApi);
  }
  // Not a `sql_database` connection → the API path (the plan-13 scaffolding,
  // this also covers a basic-auth `autocount` connection).
  if (!sql) return mockCompany({ connectionId: input.connectionId });
  const companies = allCompanies();
  const bound = companies.find((c) => c.connectionId === sql.id);
  if (bound) {
    throw new ApiError(`'${sql.database}' is already connected as company '${bound.name}'.`, 409);
  }
  if (sql.id === 'conn-sql-down') {
    // The probe could not even connect - the SANITIZED runtime message, on the field.
    const message = 'Could not connect to the database: connection refused.';
    throw new ApiError(message, 422, null, { fieldErrors: { connectionId: message } });
  }
  const holder = companies.find((c) => c.databaseName === sql.database);
  if (holder) {
    throw new ApiError(`'${sql.database}' is already connected as company '${holder.name}'.`, 409);
  }
  const companyName = PROFILE_NAMES[sql.id] ?? '';
  const company = mockCompany({
    id: `company-db-${createdCompanies.size + 1}`,
    connectionId: sql.id,
    databaseName: sql.database,
    companyName,
    name: input.name?.trim() || companyName || sql.database,
    sourceKind: 'db',
    createdAt: nowIso(),
  });
  createdCompanies.set(company.id, company);
  return { ...company };
}

/** The open-company branch (AC-08-06/07): reachability probe (mocked as
 * always-ok for a known connection), `ref_prefix` required/validated/unique,
 * `database_name = ref_prefix`, NO entity seeding. */
async function mockCreateOpenCompany(
  input: AutocountCompanyCreateInput,
  connection: AutocountApiConnection,
): Promise<AutocountCompany> {
  const companies = allCompanies();
  const bound = companies.find((c) => c.connectionId === connection.id);
  if (bound) {
    throw new ApiError(`'${connection.name}' is already connected as company '${bound.name}'.`, 409);
  }
  const prefix = (input.refPrefix ?? '').trim().toUpperCase();
  if (!prefix) {
    throw new ApiError('Reference prefix is required.', 422, null, {
      fieldErrors: { refPrefix: 'Reference prefix is required.' },
    });
  }
  if (!REF_PREFIX_RE.test(prefix)) {
    throw new ApiError('Use letters, digits and underscore only (2-32 characters).', 422, null, {
      fieldErrors: {
        refPrefix: 'Use letters, digits and underscore only (2-32 characters).',
      },
    });
  }
  const holder = companies.find((c) => c.databaseName === prefix);
  if (holder) {
    throw new ApiError(`'${prefix}' is already used by company '${holder.name}'.`, 409, null, {
      fieldErrors: { refPrefix: `'${prefix}' is already used by company '${holder.name}'.` },
    });
  }
  const company = mockCompany({
    id: `company-http-${createdOpenCompanies.size + 1}`,
    connectionId: connection.id,
    databaseName: prefix,
    companyName: '',
    name: input.name?.trim() || connection.name,
    sourceKind: 'http',
    createdAt: nowIso(),
  });
  createdOpenCompanies.set(company.id, company);
  return { ...company };
}

/** Test seam: forget every S2 session state (the Vitest suite isolates cases). */
export function resetEtlMockState(): void {
  etlOverlays.clear();
  companyCodes.clear();
  mockSinks.clear();
  sourceImpls.clear();
  previewColumnsByQuery.clear();
  httpPreviewColumnsByKey.clear();
  etlRuns.clear();
  etlTasks.clear();
  createdCompanies.clear();
  createdOpenCompanies.clear();
  dbSeeded = false;
  mockRepushInFlightRunId = null;
}

export const mockAutocountService: AutocountService = {
  listCompanies(query: AutocountListQuery = {}): Promise<ListResult<AutocountCompany>> {
    const all = allCompanies();
    return Promise.resolve({ data: all, total: all.length, page: query.page ?? 0 });
  },

  getCompany(id: string): Promise<AutocountCompanyDetail> {
    const company = mockCompanyState(id);
    const entities = companyEntities(company).map((e) => applyEntityOverlay(id, e));
    return Promise.resolve(
      applyDetailOverlay({
        company: { ...company, documentPrerequisites: computeDocumentPrerequisites(entities) },
        entities,
      }),
    );
  },

  createCompany(input: AutocountCompanyCreateInput): Promise<AutocountCompany> {
    return mockCreateCompany(input);
  },

  async updateEntityConfig(
    companyId: string,
    entityType: string,
    input: AutocountEntityConfigUpdate,
  ): Promise<AutocountEntityConfig> {
    if (input.sourceImpl && input.sourceImpl !== 'autocount_read' && input.sourceImpl !== 'sql_db') {
      throw new ApiError('Unknown source.', 422);
    }
    if (input.sourceImpl) noteSourceImpl(companyId, entityType, input.sourceImpl);
    const detail = await this.getCompany(companyId);
    const entity = detail.entities.find((e) => e.entityType === entityType);
    if (!entity) throw new ApiError('Entity not found.', 404);
    return {
      ...entity,
      initialLookbackDays: input.initialLookbackDays ?? entity.initialLookbackDays,
    };
  },

  syncNow(): Promise<AutocountSyncJob> {
    return Promise.resolve({
      id: 'job-mock',
      status: 'needs_review',
      progressTotal: 172,
      progressDone: 172,
      progressFailed: 0,
      result: null,
      error: null,
      createdAt: '2026-07-21T09:00:00Z',
    });
  },

  listRuns(): Promise<ListResult<AutocountSyncRun>> {
    return Promise.resolve({ data: [], total: 0, page: 0 });
  },

  listJobs(query: AutocountJobListQuery = {}): Promise<ListResult<AutocountSyncJobBatch>> {
    const all: AutocountSyncJobBatch[] = [
      {
        jobId: 'job-1',
        companyId: 'company-1',
        companyName: 'AED VSoft',
        databaseName: 'AED_VSOFT',
        entityType: 'supplier',
        status: 'needs_review',
        progressTotal: 172,
        progressDone: 172,
        progressFailed: 0,
        createdAt: '2026-07-21T09:00:00Z',
        startedAt: '2026-07-21T09:00:01Z',
        finishedAt: '2026-07-21T09:00:12Z',
        updatedAt: '2026-07-21T09:00:12Z',
      },
      {
        jobId: 'job-2',
        companyId: 'company-1',
        companyName: 'AED VSoft',
        databaseName: 'AED_VSOFT',
        entityType: 'customer',
        status: 'done',
        progressTotal: 40,
        progressDone: 40,
        progressFailed: 0,
        createdAt: '2026-07-20T09:00:00Z',
        startedAt: '2026-07-20T09:00:01Z',
        finishedAt: '2026-07-20T09:00:08Z',
        updatedAt: '2026-07-20T09:00:08Z',
      },
    ];
    const status = query.status ?? 'needs_review';
    const matched = status === 'all' ? all : all.filter((j) => j.status === status);
    const page = query.page ?? 0;
    const pageSize = query.pageSize ?? 25;
    return Promise.resolve({
      data: matched.slice(page * pageSize, page * pageSize + pageSize),
      total: matched.length,
      page,
    });
  },

  listStaged(jobId: string, query: AutocountStagedQuery = {}): Promise<AutocountStagedList> {
    const all = mockStagedRecords();
    const term = (query.search ?? '').trim().toLowerCase();
    let matched = all;
    if (query.changed === true) matched = matched.filter((r) => r.hasChanges);
    else if (query.changed === false) matched = matched.filter((r) => !r.hasChanges);
    if (query.status) matched = matched.filter((r) => r.status === query.status);
    if (term) {
      matched = matched.filter((r) =>
        [r.sourceRef, r.docNo, mockName(r)]
          .filter(Boolean)
          .some((v) => String(v).toLowerCase().includes(term)),
      );
    }
    const page = query.page ?? 0;
    const pageSize = query.pageSize ?? 25;
    const start = page * pageSize;
    return Promise.resolve({
      job: {
        id: jobId,
        status: 'needs_review',
        progressTotal: all.length,
        progressDone: all.length,
        progressFailed: all.filter((r) => r.status === 'FAILED').length,
        result: null,
        error: null,
        createdAt: '2026-07-21T09:00:00Z',
      },
      data: matched.slice(start, start + pageSize),
      total: matched.length,
      noChangeCount: all.filter((r) => !r.hasChanges).length,
    });
  },

  refetchHistory(_companyId, entityType): Promise<AutocountEntityConfig> {
    return Promise.resolve({
      id: 'e-mock',
      entityType,
      syncMode: 'SCHEDULED_REVIEW',
      sourceImpl: 'autocount_read',
      recordCap: 200,
      initialLookbackDays: 30,
      enabled: true,
      lastSuccessAt: null,
      lastAttemptAt: null,
      watermarkAt: null, // the reset - the first-run window is live again
      consecutiveFailures: 0,
      lastError: null,
      etlStatus: 'draft',
    });
  },

  preview(jobId: string): Promise<AutocountPreviewResult> {
    if (jobId.includes('logging') || jobId.includes('nopreview')) {
      return Promise.resolve({
        jobId,
        preview: {
          previewable: false,
          sink: 'logging',
          reason:
            'No consumer is configured for this company, so there is nothing to preview.',
        },
      });
    }
    if (jobId.includes('fail')) {
      return Promise.reject(
        new ApiError(
          'The dry run against the consumer failed, so this batch cannot be approved yet. Nothing was written - resolve the consumer error first.',
          502,
        ),
      );
    }
    return Promise.resolve(previewablePayload(jobId));
  },

  approve(jobId: string): Promise<AutocountApprovalResult> {
    return Promise.resolve({ jobId, result: { pushed: 172 } });
  },

  discard(jobId: string): Promise<AutocountApprovalResult> {
    return Promise.resolve({ jobId, result: { discarded: 172 } });
  },

  updateSinkTarget(
    companyId: string,
    input: AutocountSinkTargetInput,
  ): Promise<AutocountCompany> {
    guardSinkTarget(input);
    noteSinkTarget(companyId, input);
    mockSinks.set(companyId, {
      sinkImpl: input.sinkImpl,
      sinkConnectionId: input.sinkImpl === 'sorento' ? input.sinkConnectionId ?? null : null,
    });
    return Promise.resolve(applyCompanyOverlay(mockCompanyState(companyId)));
  },

  getMapping(companyId: string, entityType: string): Promise<AutocountMappingView> {
    return Promise.resolve(mockMappingView(entityType, sourceImpls.get(taskKey(companyId, entityType))));
  },

  updateMapping(
    companyId: string,
    entityType: string,
    input: AutocountMappingUpdate,
  ): Promise<AutocountMappingView> {
    const view = mockMappingView(entityType, sourceImpls.get(taskKey(companyId, entityType)));
    const headerRows = input.rows.filter((r) => (r.scope ?? 'header') === 'header');
    // Mirrors the real service's backward-compat fold (security re-review
    // should-fix, sprint-5/02 review round): the dedicated `lineRows` field
    // wins when present (even `[]`); a caller still folding scope='line'
    // items into `rows` (the pre-existing shape) is honoured the same way
    // for one release.
    const lineRows =
      input.lineRows !== undefined
        ? input.lineRows
        : input.rows.filter((r) => r.scope === 'line');

    // A required Sorento target left unmapped is the real failure the editor
    // guards; a target outside the accepted set is a 422 server-side. The mock
    // rejects an unknown target so the surfaced-error path is testable.
    const acceptedHeader = new Set(view.sorentoFields.map((f) => f.field));
    for (const row of headerRows) {
      if (!acceptedHeader.has(row.sorentoField)) {
        return Promise.reject(
          new ApiError(
            `'${row.sorentoField}' is not a Sorento field accepted for ${entityType}.`,
            422,
          ),
        );
      }
    }

    // Line rows (sprint-5/02, AC-02-03): only accepted line targets, ref
    // pairing locked, and source_ref/product_ref/qty_ordered required the
    // moment any line row is saved.
    if (lineRows.length > 0) {
      const acceptedLine = new Set(view.lineSorentoFields.map((f) => f.field));
      for (const row of lineRows) {
        if (!acceptedLine.has(row.sorentoField)) {
          return Promise.reject(
            new ApiError(
              `'${row.sorentoField}' is not a line field accepted for ${entityType}.`,
              422,
            ),
          );
        }
        if (row.sorentoField === 'product_ref' && row.transform !== 'ref_product') {
          return Promise.reject(new ApiError("'product_ref' must use the Product ref transform.", 422));
        }
        if (row.sorentoField === 'warehouse_ref' && row.transform !== 'ref_warehouse') {
          return Promise.reject(new ApiError("'warehouse_ref' must use the Warehouse ref transform.", 422));
        }
      }
      const mappedTargets = new Set(lineRows.map((r) => r.sorentoField));
      for (const required of ['source_ref', 'product_ref', 'qty_ordered']) {
        if (!mappedTargets.has(required)) {
          return Promise.reject(
            new ApiError(`Line mapping is missing the required field '${required}'.`, 422),
          );
        }
      }
    }

    const toRows = (rows: AutocountMappingWriteRow[], scope: 'header' | 'line', fields: typeof view.sorentoFields) =>
      rows.map((row) => ({
        sourcePath: row.sourcePath,
        transform: row.transform,
        formula: row.formula?.trim() ? row.formula.trim() : null,
        sorentoField: row.sorentoField,
        canonicalField: row.sorentoField,
        scope,
        isRequired: fields.find((f) => f.field === row.sorentoField)?.required ?? false,
        // B1 (final review round) - echo the saved isEnabled instead of
        // hardcoding true, so the mock round-trips a disabled row like real.
        isEnabled: row.isEnabled ?? true,
      }));

    return Promise.resolve({
      ...view,
      rows: [
        ...toRows(headerRows, 'header', view.sorentoFields),
        ...toRows(lineRows, 'line', view.lineSorentoFields),
      ],
    });
  },

  testFormula(
    _companyId: string,
    _entityType: string,
    formula: string,
    value: unknown,
  ): Promise<AutocountFormulaTestResult> {
    // Mirrors the server: the same safe evaluator, a named error, never a throw.
    return Promise.resolve(evalFormula(formula, value));
  },

  simulateMapping(
    companyId: string,
    entityType: string,
    record: Record<string, unknown>,
    rows?: AutocountMappingWriteRow[],
    lines?: Array<Record<string, unknown>>,
  ): Promise<AutocountSimulateResult> {
    // A light stand-in for the real MappingEngine: evaluate each draft (or saved)
    // deliverable row's formula/passthrough over the flat mock record so the
    // record-in → record-out preview + per-field errors are tunable with no
    // backend. The real engine is authoritative; this only drives the UI states.
    const view = mockMappingView(entityType, sourceImpls.get(taskKey(companyId, entityType)));
    type RowSpec = { sourcePath: string; formula: string | null; canonicalField: string };
    const toSpec = (r: {
      sourcePath: string;
      formula?: string | null;
      sorentoField: string | null;
    }): RowSpec => ({
      sourcePath: r.sourcePath,
      formula: r.formula ?? null,
      canonicalField: r.sorentoField as string,
    });
    const headerSource: RowSpec[] = rows
      ? rows.filter((r) => (r.scope ?? 'header') === 'header').map(toSpec)
      : view.rows.filter((r) => r.scope === 'header' && r.sorentoField).map(toSpec);
    const lineSource: RowSpec[] = rows
      ? rows.filter((r) => r.scope === 'line').map(toSpec)
      : view.rows.filter((r) => r.scope === 'line' && r.sorentoField).map(toSpec);

    // Lines pass FIRST (AC-02-07) - both the mapped line canonical rows AND
    // the per-field results, then the five aggregates they feed into the
    // header pass.
    const lineFields: AutocountSimulateFieldResult[][] = [];
    const lineCanonical: Record<string, unknown>[] = [];
    for (const lineRecord of lines ?? []) {
      const fields: AutocountSimulateFieldResult[] = [];
      const out: Record<string, unknown> = {};
      for (const r of lineSource) {
        const raw = lineRecord[r.sourcePath];
        const present = raw !== undefined;
        const formula = r.formula?.trim() ? r.formula.trim() : 'value';
        const evaluated = present ? evalFormula(formula, raw) : { ok: true, output: null, error: null };
        if (evaluated.ok && present) out[r.canonicalField] = evaluated.output;
        fields.push({
          scope: 'line',
          sourcePath: r.sourcePath,
          canonicalField: r.canonicalField,
          present,
          ok: evaluated.ok,
          value: evaluated.output,
          error: evaluated.error,
        });
      }
      lineFields.push(fields);
      lineCanonical.push(out);
    }

    const asNumber = (v: unknown): number => (typeof v === 'number' && Number.isFinite(v) ? v : 0);
    const sum = (values: number[]): number => values.reduce((a, b) => a + b, 0);
    const fulfilledField = fulfilledFieldFor(entityType);
    const outstandingPerLine = lineCanonical.map((l) =>
      Math.max(0, asNumber(l.qty_ordered) - asNumber(l[fulfilledField])),
    );
    const aggregateFacts: Record<string, unknown> = {
      'lines.count': lineCanonical.length,
      'lines.open_count': outstandingPerLine.filter((v) => v > 0).length,
      'lines.ordered_sum': sum(lineCanonical.map((l) => asNumber(l.qty_ordered))),
      'lines.fulfilled_sum': sum(lineCanonical.map((l) => asNumber(l[fulfilledField]))),
      'lines.outstanding_sum': sum(outstandingPerLine),
    };

    // Header runs AFTER lines - every header row's formula can reference its
    // own row value (`value`) AND any raw header column / `lines.*`
    // aggregate BY NAME (sprint-5/02, AC-02-07/20).
    const headerFacts: Record<string, unknown> = { ...record, ...aggregateFacts };
    const headerFields: AutocountSimulateFieldResult[] = [];
    const out: Record<string, unknown> = {};
    let ok = true;
    let status: string | null = null;
    for (const r of headerSource) {
      const raw = record[r.sourcePath];
      const present = raw !== undefined;
      const formula = r.formula?.trim() ? r.formula.trim() : 'value';
      const evaluated = present
        ? evalFormula(formula, raw, headerFacts)
        : { ok: true, output: null, error: null };
      if (!evaluated.ok) ok = false;
      if (evaluated.ok && present) {
        out[r.canonicalField] = evaluated.output;
        if (r.canonicalField === 'status' && typeof evaluated.output === 'string') {
          status = evaluated.output;
        }
      }
      headerFields.push({
        scope: 'header',
        sourcePath: r.sourcePath,
        canonicalField: r.canonicalField,
        present,
        ok: evaluated.ok,
        value: evaluated.output,
        error: evaluated.error,
      });
    }
    if (lineSource.length > 0) {
      out.lines = lineCanonical;
    }

    return Promise.resolve({
      ok,
      sourceRef: String(record.AccNo ?? record.DocNo ?? ''),
      docNo: (record.DocNo as string | undefined) ?? null,
      record: ok ? out : null,
      headerFields,
      lineFields,
      status,
      errors: ok
        ? []
        : headerFields.filter((f) => !f.ok).map((f) => ({ field: f.canonicalField, message: f.error })),
    });
  },

  listMappingPresets(companyId: string, entityType: string): Promise<AutocountMappingPreset[]> {
    const company = mockCompanyState(companyId);
    return Promise.resolve(mockMappingPresets(company.databaseName, entityType));
  },

  // ── direct-DB ETL (plan 22 S1) ─────────────────────────────────────────────

  async listSqlConnections(): Promise<AutocountSqlConnection[]> {
    await pause(150);
    return SQL_CONNECTIONS.map((c) => ({ ...c }));
  },

  async getSqlSchema(connectionId: string): Promise<AutocountSqlSchema> {
    await pause(350);
    const connection = SQL_CONNECTIONS.find((c) => c.id === connectionId);
    if (!connection) throw new ApiError('Connection not found.', 404);
    if (connection.id === 'conn-sql-down') {
      // The sanitized failure shape (AC-22-02/30): no host, no credentials.
      throw new ApiError(
        'Could not connect to the database: connection refused.',
        502,
      );
    }
    return mockSqlSchema(connection);
  },

  // `opts` (bindDocKey/docKey) is part of the interface (plan 22 S5) but the
  // mock's table-name-regex preview needs no real parameter binding to
  // return realistic columns for a `:doc_key`-carrying line query.
  async previewSqlQuery(connectionId: string, query: string): Promise<AutocountSqlPreview> {
    await pause(450);
    const connection = SQL_CONNECTIONS.find((c) => c.id === connectionId);
    if (!connection) throw new ApiError('Connection not found.', 404);
    if (connection.id === 'conn-sql-down') {
      throw new ApiError(
        'Could not connect to the database: connection refused.',
        502,
      );
    }
    const preview = runMockPreview(query);
    previewColumnsByQuery.set(normalizeQuery(query), preview.columns.map((c) => c.name));
    return preview;
  },

  async getEtlTask(companyId: string, entityType: string): Promise<AutocountEtlTask> {
    await pause(200);
    return cloneJson(applyTaskOverlay(etlTaskFor(companyId, entityType)));
  },

  async updateEtlTask(
    companyId: string,
    entityType: string,
    input: AutocountEtlTaskUpdate,
  ): Promise<AutocountEtlTask> {
    await pause(250);
    const current = etlTaskFor(companyId, entityType);
    let cfg = input.sourceConfig;
    const key = taskKey(companyId, entityType);
    const previousImpl: 'sql_db' | 'autocount_http' =
      sourceImpls.get(key) === 'autocount_http' ? 'autocount_http' : 'sql_db';
    const newImpl = input.sourceImpl ?? previousImpl;
    const company = mockCompanyState(companyId);
    // A DB company reads ONLY from its own connection for a `sql_db` task
    // (AC-01-09/10); an `autocount_http` task on a DB company may reference
    // ANY open connection of the tenant (AC-08-13 narrows the lock to
    // `sql_db` only). The API-only GRN envelope has no database path at all.
    if (company.sourceKind === 'db' && newImpl === 'sql_db') {
      if (entityType === 'goods_received_note') {
        throw new ApiError('Goods received notes are not available on a database company.', 422);
      }
      if (!cfg.connectionId) cfg = { ...cfg, connectionId: company.connectionId };
      else if (cfg.connectionId !== company.connectionId) {
        const message = 'A database company reads only from its own connection.';
        throw new ApiError(message, 422, null, { fieldErrors: { connectionId: message } });
      }
    }
    if (newImpl === 'autocount_http') {
      const conn = httpConnectionFor(cfg.connectionId ?? '');
      if (!conn || conn.auth !== 'none') {
        const message = 'Choose an open (no-auth) AutoCount connection.';
        throw new ApiError(message, 422, null, { fieldErrors: { connectionId: message } });
      }
      if (!cfg.path?.trim()) {
        const message = 'Enter an endpoint path.';
        throw new ApiError(message, 422, null, { fieldErrors: { path: message } });
      }
    }
    // Mirrors the save-time guard (AC-22-11/S5, line key/product columns
    // moved OFF this guard and onto the mapping save path in sprint-5/02
    // AC-02-03/05): documents need a from-date, a watermark column
    // (line-change detection - AutoCount stamps a header's LastModified on
    // any line edit), and a date-floor column. HTTP entities are never
    // documents (AC_HTTP_ENTITY_TYPES), so this never fires for one.
    if (isDocumentEntity(entityType)) {
      const fieldErrors: Record<string, string> = {};
      if (!cfg.fromDate) fieldErrors.fromDate = 'From date is required for documents.';
      if (!cfg.watermarkColumn) {
        fieldErrors.watermarkColumn = 'A watermark column is required for documents.';
      }
      if (!cfg.docDateColumn) fieldErrors.docDateColumn = "Choose the document's date column.";
      if (Object.keys(fieldErrors).length > 0) {
        throw new ApiError('The task could not be saved. Fix the highlighted fields.', 422, null, {
          fieldErrors,
        });
      }
    }
    // AC-08-28 - changing the task's impl (either direction), connection or
    // (for HTTP) path sets an ACTIVE task back to draft (must Test +
    // re-activate); `ac_row_hash`-equivalent tracking (the mock has none to
    // clear) is untouched so the first reconcile after a switch reports
    // updates rather than phantom deletes when the key is unchanged.
    const implOrSourceChanged =
      newImpl !== previousImpl ||
      cfg.connectionId !== current.sourceConfig.connectionId ||
      (newImpl === 'autocount_http' && cfg.path !== current.sourceConfig.path);
    const next: AutocountEtlTask = {
      ...current,
      sourceConfig: cloneJson(cfg),
    };
    etlTasks.set(key, next);
    if (input.sourceImpl) noteSourceImpl(companyId, entityType, input.sourceImpl);
    noteTaskSaved(companyId, entityType, cfg, newImpl, implOrSourceChanged);
    return cloneJson(applyTaskOverlay(next));
  },

  // ── direct-DB ETL (plan 22 S2) ─────────────────────────────────────────────

  async previewEtlTask(companyId, entityType) {
    const [detail, task] = await Promise.all([
      this.getCompany(companyId),
      this.getEtlTask(companyId, entityType),
    ]);
    return mockPreviewEtlTask(detail.company, task);
  },

  async activateEtlTask(companyId, entityType) {
    await pause(200);
    const [detail, task] = await Promise.all([
      this.getCompany(companyId),
      this.getEtlTask(companyId, entityType),
    ]);
    return mockActivate(detail.company, task);
  },

  async pauseEtlTask(companyId, entityType) {
    await pause(250);
    return mockPause(await this.getEtlTask(companyId, entityType));
  },

  async resumeEtlTask(companyId, entityType) {
    await pause(250);
    return mockResume(await this.getEtlTask(companyId, entityType));
  },

  async runEtlTaskNow(companyId, entityType) {
    await pause(500);
    const [detail, task] = await Promise.all([
      this.getCompany(companyId),
      this.getEtlTask(companyId, entityType),
    ]);
    return mockRunNow(detail.company, task);
  },

  async listEtlRuns(companyId, entityType, query) {
    await pause(200);
    return mockListEtlRuns(companyId, entityType, query);
  },

  // ── "Re-push all" (plan sprint-5/07, AC-07-20) - PHASE 1 MOCK is the spec
  // for the S2b backend, per `setMockRepushInFlight` above. ─────────────────
  async repushEtlTask(companyId, entityType) {
    await pause(300);
    if (mockRepushInFlightRunId) {
      const runId = mockRepushInFlightRunId;
      throw new ApiError('A run is already in progress for this task.', 409, null, {
        message: 'A run is already in progress for this task.',
        runningRunId: runId,
      });
    }
    const task = await this.getEtlTask(companyId, entityType);
    if (task.etlStatus === 'draft') {
      throw new ApiError('Activate the task first - a draft has nothing to re-push.', 409);
    }
    const impl = sourceImpls.get(taskKey(companyId, entityType)) ?? 'sql_db';
    if (impl !== 'sql_db') {
      throw new ApiError('Re-push applies to database tasks only.', 409);
    }
    return {
      clearedCount: 148068,
      nextReconcileAt:
        task.etlStatus === 'active' ? new Date(Date.now() + 60_000).toISOString() : null,
      status: task.etlStatus,
    };
  },

  // ── open REST API source (sprint-5/08, S1) ──────────────────────────────

  async listApiConnections(): Promise<AutocountApiConnection[]> {
    // EVERY `autocount` connection, bound or not (AC-08-15) - the connect
    // form's picker excludes already-bound ones ITSELF (the same "taken" set
    // `useAutocountSourceConnections` already builds from `listCompanies()`);
    // the task Source tab needs the bound ones too, to badge/label a locked
    // company connection or a DB company's free cross-tenant pick.
    await pause(150);
    return HTTP_API_CONNECTIONS.map((c) => ({ ...c }));
  },

  async previewHttp(input: HttpPreviewInput): Promise<HttpPreview> {
    const preview = await mockPreviewHttp(input);
    httpPreviewColumnsByKey.set(
      httpPreviewKey(input.connectionId, input.path, input.distinctOf),
      preview.columns.map((c) => c.name),
    );
    // Mirrors the real backend's `preview_http` (sprint-5/08 review round
    // 7): a clean Test that names both `companyId`/`entityType` ALSO stamps
    // `resultColumns`/`lastPreviewAt` on the task and echoes it back, so the
    // editor's `apply()` path is exercised the same way against the mock.
    //
    // Round 8 nit: the backend only stamps/echoes when an `ac_entity_config`
    // row already exists (`self.configs.get(...)` is not `None`) - a
    // never-configured entity's task stays `null`. `etlTaskFor` would happily
    // auto-create a blank draft here, which the OLD code then echoed back as
    // if it were a real, already-anchored task; gate on `etlTasks` already
    // holding a row for the pair so a truly never-touched entity gets the
    // bare preview, matching the backend.
    if (input.companyId && input.entityType && etlTasks.has(taskKey(input.companyId, input.entityType))) {
      const o = overlayFor(input.companyId, input.entityType);
      o.resultColumns = preview.columns.map((c) => c.name);
      o.lastPreviewAt = nowIso();
      return {
        ...preview,
        task: cloneJson(applyTaskOverlay(etlTaskFor(input.companyId, input.entityType))),
      };
    }
    return preview;
  },
};

/** A realistic supplier/customer mapping view for the editor's tunable states. */
function masterMappingView(entityType: string): AutocountMappingView {
  return {
    entityType,
    rows: [
      {
        sourcePath: 'AccNo',
        transform: 'string',
        formula: null,
        sorentoField: 'code',
        canonicalField: 'code',
        scope: 'header',
        isRequired: true,
        isEnabled: true,
      },
      {
        sourcePath: 'CompanyName',
        transform: 'string',
        formula: null,
        sorentoField: 'name',
        canonicalField: 'name',
        scope: 'header',
        isRequired: true,
        isEnabled: true,
      },
      {
        sourcePath: 'IsActive',
        transform: 't_f_bool',
        formula: 'if(value == "T", true, false)',
        sorentoField: 'is_active',
        canonicalField: 'is_active',
        scope: 'header',
        isRequired: true,
        isEnabled: true,
      },
      {
        sourcePath: 'EmailAddress',
        transform: 'string',
        formula: null,
        sorentoField: 'email',
        canonicalField: 'email',
        scope: 'header',
        isRequired: false,
        isEnabled: true,
      },
      // A provenance row - stored canonically, never delivered to Sorento.
      {
        sourcePath: 'Data.0.LastModified',
        transform: 'slash_datetime',
        formula: null,
        sorentoField: null,
        canonicalField: 'last_modified',
        scope: 'header',
        isRequired: false,
        isEnabled: true,
      },
    ],
    sorentoFields: [
      { field: 'code', required: true },
      { field: 'name', required: true },
      { field: 'is_active', required: true },
      { field: 'email', required: false },
      { field: 'phone_number', required: false },
      { field: 'tax_id', required: false },
    ],
    acFields: [
      'AccNo',
      'CompanyName',
      'EmailAddress',
      'IsActive',
      'Mobile',
      'TIN',
      'Data.0.AutoKey',
      'Data.0.LastModified',
    ],
    lineSorentoFields: [],
    lineAcFields: [],
  };
}

// ── document mapping (sprint-5/02, S1 - AC-02-01/02/16/17) - PHASE 1 MOCK ────
//
// One canonical field spec drives BOTH the "current mapping" fixture
// (`documentMappingView`) and the "Use preset" insert (`listMappingPresets`
// via `documentPreset`) - a single source of truth so the two can never
// silently drift, matching `MappingEngine.project_document`'s eventual (S2)
// backend contract.

interface DocFieldSpec {
  sourcePath: string;
  sorentoField: string;
  transform: string;
  formula?: string | null;
  required?: boolean;
}

interface DocumentPresetSpec {
  label: string;
  headerQuery: string;
  lineQuery: string;
  keyColumns: string[];
  watermarkColumn: string;
  docDateColumn: string;
  fromDate: string;
  filterFormula: string | null;
  header: DocFieldSpec[];
  line: DocFieldSpec[];
  /**
   * The LINE catalog's accepted targets (sprint-5/06, AC-06-10) - defaults to
   * `line`'s own mapped fields when absent (every prior preset's catalog IS
   * exactly its mapped rows). PO/SPO diverge: four `from_so_external_*` input
   * fields are catalog-OFFERED but never preset-mapped (operator additions
   * only, AC-06-24), so their preset needs a target list wider than `line`.
   */
  lineTargets?: AutocountSorentoField[];
}

const SO_PRESET: DocumentPresetSpec = {
  label: 'AutoCount SO',
  headerQuery:
    'SELECT DocKey, DocNo, DebtorAutoKey, DebtorCode, DebtorName, SalesAgent, DocDate, ' +
    'RequestedDeliveryDate, Note, Cancelled, LastModified FROM {database}.dbo.SO_Header',
  lineQuery:
    'SELECT DtlKey, ItemAutoKey, ItemCode, Description, LocationAutoKey, Location, Qty, ' +
    'TransferedQty, UnitPrice, DiscountAmt, SubTotal, UOM, DeliveryDate, Seq ' +
    'FROM {database}.dbo.SO_Dtl WHERE DocKey = :doc_key',
  keyColumns: ['DocKey'],
  watermarkColumn: 'LastModified',
  docDateColumn: 'DocDate',
  fromDate: '',
  filterFormula: null,
  header: [
    { sourcePath: 'DocNo', sorentoField: 'so_number', transform: 'string', required: true },
    { sourcePath: 'DebtorAutoKey', sorentoField: 'customer_ref', transform: 'ref_customer', required: true },
    { sourcePath: 'SalesAgent', sorentoField: 'sales_agent_ref', transform: 'ref_sales_agent' },
    { sourcePath: 'DocDate', sorentoField: 'doc_date', transform: 'date' },
    { sourcePath: 'RequestedDeliveryDate', sorentoField: 'requested_delivery_date', transform: 'date' },
    { sourcePath: 'Note', sorentoField: 'internal_note', transform: 'string' },
    { sourcePath: 'Cancelled', sorentoField: 'status', transform: 'string', formula: DEFAULT_STATUS_FORMULA },
    { sourcePath: 'DebtorCode', sorentoField: 'customer_code', transform: 'string' },
    { sourcePath: 'DebtorName', sorentoField: 'customer_name', transform: 'string' },
    { sourcePath: 'SalesAgent', sorentoField: 'agent_code', transform: 'string' },
  ],
  line: [
    { sourcePath: 'DtlKey', sorentoField: 'source_ref', transform: 'string', required: true },
    { sourcePath: 'ItemAutoKey', sorentoField: 'product_ref', transform: 'ref_product', required: true },
    { sourcePath: 'LocationAutoKey', sorentoField: 'warehouse_ref', transform: 'ref_warehouse' },
    { sourcePath: 'Qty', sorentoField: 'qty_ordered', transform: 'decimal', required: true },
    { sourcePath: 'TransferedQty', sorentoField: 'qty_delivered', transform: 'decimal' },
    { sourcePath: 'UnitPrice', sorentoField: 'unit_price', transform: 'decimal' },
    { sourcePath: 'DiscountAmt', sorentoField: 'discount', transform: 'decimal' },
    { sourcePath: 'SubTotal', sorentoField: 'line_total', transform: 'decimal' },
    { sourcePath: 'UOM', sorentoField: 'uom', transform: 'string' },
    { sourcePath: 'DeliveryDate', sorentoField: 'required_date', transform: 'date' },
    { sourcePath: 'ItemCode', sorentoField: 'product_code', transform: 'string' },
    { sourcePath: 'Description', sorentoField: 'product_name', transform: 'string' },
    { sourcePath: 'Location', sorentoField: 'warehouse_code', transform: 'string' },
    { sourcePath: 'Seq', sorentoField: 'line_number', transform: 'int' },
  ],
};

/**
 * The four `from_so_external_*` INPUT fields (never sent on the wire, UAC
 * Definitions) - the ICB (inter-company) case only, the ONE part of the
 * linkage catalog that never gets a preset row (review round nit: the other
 * six input/wire targets are now pre-mapped below, mirroring the backend
 * preset's own `PO_PRESET.line`/`SPO_PRESET.line`). Catalog-only: none of
 * these mint themselves without an operator explicitly mapping `db`, so none
 * is pre-mapped here - an operator adds the row (AC-06-24).
 */
const LINE_LINKAGE_CATALOG_ONLY_TARGETS: AutocountSorentoField[] = [
  { field: 'from_so_external_db', required: false },
  { field: 'from_so_external_doc_key', required: false },
  { field: 'from_so_external_doc_no', required: false },
  { field: 'from_so_external_line_key', required: false },
];

/** PO/SPO share the supplier-side shape (unit_cost/qty_received/currency);
 *  the family split is the filter formula + entity, not the field list. */
function purchaseFamilyPreset(entityType: 'purchase_order' | 'shipping_order'): DocumentPresetSpec {
  const isSpo = entityType === 'shipping_order';
  const line: DocFieldSpec[] = [
    { sourcePath: 'DtlKey', sorentoField: 'source_ref', transform: 'string', required: true },
    { sourcePath: 'ItemAutoKey', sorentoField: 'product_ref', transform: 'ref_product', required: true },
    { sourcePath: 'LocationAutoKey', sorentoField: 'warehouse_ref', transform: 'ref_warehouse' },
    { sourcePath: 'Qty', sorentoField: 'qty_ordered', transform: 'decimal', required: true },
    { sourcePath: 'ReceivedQty', sorentoField: 'qty_received', transform: 'decimal' },
    { sourcePath: 'UnitPrice', sorentoField: 'unit_cost', transform: 'decimal' },
    { sourcePath: 'UOM', sorentoField: 'uom', transform: 'string' },
    { sourcePath: 'ExpectedDate', sorentoField: 'expected_date', transform: 'date' },
    { sourcePath: 'ItemCode', sorentoField: 'product_code', transform: 'string' },
    { sourcePath: 'Description', sorentoField: 'product_name', transform: 'string' },
    { sourcePath: 'Location', sorentoField: 'warehouse_code', transform: 'string' },
    // sprint-5/06 (AC-06-14, review round nit) - the six line-linkage preset
    // rows, mirroring the backend preset (`PO_PRESET.line`/`SPO_PRESET.line`,
    // `modules/autocount/presets.py`) byte-for-byte: `from_so_numbers` already
    // existed here (plan 22 S5, placeholder `string` transform before AC-06-01
    // made it `string_list`); the other five are new.
    { sourcePath: 'FromSODocKey', sorentoField: 'from_so_doc_key', transform: 'int' },
    { sourcePath: 'FromSODtlKey', sorentoField: 'from_so_line_key', transform: 'int' },
    { sourcePath: 'FromSODocList', sorentoField: 'from_so_numbers', transform: 'string_list' },
    { sourcePath: 'FromPODocKey', sorentoField: 'from_po_doc_key', transform: 'int' },
    { sourcePath: 'FromPODtlKey', sorentoField: 'from_po_line_key', transform: 'int' },
    { sourcePath: 'FromPODocNo', sorentoField: 'from_po_number', transform: 'string' },
    { sourcePath: 'Seq', sorentoField: 'line_number', transform: 'int' },
  ];
  return {
    label: isSpo ? 'AutoCount SPO' : 'AutoCount PO',
    headerQuery:
      'SELECT DocKey, DocNo, CreditorAutoKey, CreditorCode, CreditorName, PurchaseAgent, DocDate, ' +
      'ExpectedDate, UDF_Currency, CurrencyCode, Cancelled, LastModified FROM {database}.dbo.PO_Header',
    lineQuery:
      'SELECT DtlKey, ItemAutoKey, ItemCode, Description, LocationAutoKey, Location, Qty, ' +
      'ReceivedQty, UnitPrice, UOM, ExpectedDate, FromSODocList, Seq ' +
      'FROM {database}.dbo.PO_Dtl WHERE DocKey = :doc_key',
    keyColumns: ['DocKey'],
    watermarkColumn: 'LastModified',
    docDateColumn: 'DocDate',
    fromDate: '',
    filterFormula: isSpo
      ? 'startswith(upper(trim(DocNo)), "SPO-")'
      : 'not(startswith(upper(trim(DocNo)), "SPO-"))',
    header: [
      {
        sourcePath: 'DocNo',
        sorentoField: isSpo ? 'spo_number' : 'po_number',
        transform: 'string',
        required: true,
      },
      { sourcePath: 'CreditorAutoKey', sorentoField: 'supplier_ref', transform: 'ref_supplier', required: true },
      { sourcePath: 'DocDate', sorentoField: isSpo ? 'issue_date' : 'doc_date', transform: 'date' },
      { sourcePath: 'ExpectedDate', sorentoField: 'expected_date', transform: 'date' },
      {
        sourcePath: 'UDF_Currency',
        sorentoField: 'currency',
        transform: 'string',
        formula: 'coalesce(UDF_Currency, CurrencyCode, "CNY")',
      },
      { sourcePath: 'Cancelled', sorentoField: 'status', transform: 'string', formula: DEFAULT_STATUS_FORMULA },
      { sourcePath: 'CreditorCode', sorentoField: 'supplier_code', transform: 'string' },
      { sourcePath: 'CreditorName', sorentoField: 'supplier_name', transform: 'string' },
      { sourcePath: 'PurchaseAgent', sorentoField: 'agent_code', transform: 'string' },
    ],
    line,
    // sprint-5/06 (AC-06-10) - the LINE catalog offers the eight input
    // fields + `from_so_numbers` + `from_po_number` (ten total); the four
    // `from_so_external_*` names never get a preset row (AC-06-24), so the
    // catalog is wider than `line` here - every prior preset's catalog
    // stayed exactly its mapped rows (the `lineTargets` default below).
    lineTargets: [
      ...line.map((f) => ({ field: f.sorentoField, required: Boolean(f.required) })),
      ...LINE_LINKAGE_CATALOG_ONLY_TARGETS,
    ],
  };
}

const DOCUMENT_PRESETS: Record<string, DocumentPresetSpec> = {
  sales_order: SO_PRESET,
  purchase_order: purchaseFamilyPreset('purchase_order'),
  shipping_order: purchaseFamilyPreset('shipping_order'),
};

/** The entity's fulfilled-quantity line field (AC-02-07) - `qty_delivered`
 *  for a sales order, `qty_received` for a purchase/shipping order. */
function fulfilledFieldFor(entityType: string): string {
  return entityType === 'sales_order' ? 'qty_delivered' : 'qty_received';
}

/** A document's "current mapping" fixture - every preset field, already
 *  mapped and enabled (a realistic ALREADY-CONFIGURED task). */
function documentMappingView(entityType: string): AutocountMappingView {
  const spec = DOCUMENT_PRESETS[entityType];
  const toRows = (fields: DocFieldSpec[], scope: 'header' | 'line') =>
    fields.map((f) => ({
      sourcePath: f.sourcePath,
      transform: f.transform,
      formula: f.formula ?? null,
      sorentoField: f.sorentoField,
      canonicalField: f.sorentoField,
      scope,
      isRequired: Boolean(f.required),
      isEnabled: true,
    }));
  return {
    entityType,
    rows: [...toRows(spec.header, 'header'), ...toRows(spec.line, 'line')],
    sorentoFields: spec.header.map((f) => ({ field: f.sorentoField, required: Boolean(f.required) })),
    acFields: spec.header.map((f) => f.sourcePath),
    lineSorentoFields:
      spec.lineTargets ?? spec.line.map((f) => ({ field: f.sorentoField, required: Boolean(f.required) })),
    lineAcFields: spec.line.map((f) => f.sourcePath),
  };
}

/**
 * An open REST API master's mapping view (sprint-5/08, AC-08-16/21) - seeded
 * straight from `HTTP_PRESETS[entityType].mapping`, the SAME table the
 * Source tab's preset pre-fill reads (one source of truth, never a second
 * copy). No document family here (AC_HTTP_ENTITY_TYPES has none), so every
 * row is header-scope and there are no line fields.
 */
function httpMasterMappingView(entityType: string): AutocountMappingView {
  const preset = HTTP_PRESETS[entityType];
  const rows = preset.mapping.map((m) => ({
    sourcePath: m.sourcePath,
    transform: m.transform,
    formula: null,
    sorentoField: m.canonicalField,
    canonicalField: m.canonicalField,
    scope: 'header' as const,
    isRequired: Boolean(m.required),
    isEnabled: true,
  }));
  return {
    entityType,
    rows,
    sorentoFields: rows.map((r) => ({ field: r.canonicalField, required: r.isRequired })),
    acFields: Array.from(new Set(preset.mapping.map((m) => m.sourcePath))),
    lineSorentoFields: [],
    lineAcFields: [],
  };
}

/**
 * `customer` is the ONE entity type both the legacy vendor-login path
 * (`autocount_read`, `masterMappingView` - AccNo/CompanyName/IsActive/
 * EmailAddress, unchanged since plan 15) AND the open REST API path
 * (`autocount_http`, AC-08-16) can configure - dispatch on the RESOLVED
 * impl for that one collision; every other `HTTP_PRESETS` entity has no
 * vendor-path meaning at all, so it always reads its HTTP preset.
 */
function mockMappingView(entityType: string, impl?: string): AutocountMappingView {
  if (isDocumentEntity(entityType) && DOCUMENT_PRESETS[entityType]) {
    return documentMappingView(entityType);
  }
  if (HTTP_PRESETS[entityType] && (impl === 'autocount_http' || entityType !== 'customer')) {
    return httpMasterMappingView(entityType);
  }
  return masterMappingView(entityType);
}

/** `GET /autocount/presets/{entityType}` (S3 backend) - the mock returns the
 *  ONE preset for this document entity, `{database}` already substituted. */
function mockMappingPresets(databaseName: string, entityType: string): AutocountMappingPreset[] {
  const spec = DOCUMENT_PRESETS[entityType];
  if (!spec) return [];
  return [
    {
      entityType,
      label: spec.label,
      headerQuery: spec.headerQuery.replace('{database}', databaseName),
      lineQuery: spec.lineQuery.replace('{database}', databaseName),
      keyColumns: spec.keyColumns,
      watermarkColumn: spec.watermarkColumn,
      docDateColumn: spec.docDateColumn,
      fromDate: spec.fromDate || null,
      filterFormula: spec.filterFormula,
    },
  ];
}

// sprint-5/02 S3 closed the PHASE 1 MOCK entirely: `simulateMapping`'s
// `lines=` overload and `listMappingPresets` (`GET /autocount/presets/
// {entityType}`) are both real server-side now (`modules/autocount/
// routers/sync.py`, `presets.py`), same as `getMapping`/`updateMapping`
// since S2. `autocount-service.ts` exports `realAutocountService` bare -
// there is no more mock overlay to bind. `mockMappingPresets`/
// `documentMappingView`/`mockMappingView` above remain as the Vitest
// fixture data (`mockAutocountService`) the builder's frontend-first tests
// exercise directly.
