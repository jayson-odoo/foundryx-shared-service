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
 */
import { ApiError } from '@/lib/api-client';
import { testFormula as evalFormula } from '@/lib/autocount-formula';
import {
  MIN_RECONCILE_HOURS,
  RECONCILE_TIME_RE,
  incrementalFloorMinutes,
  isDocumentEntity,
} from '@/lib/autocount-etl';
import type {
  AutocountApprovalResult,
  AutocountCompany,
  AutocountCompanyDetail,
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
  AutocountMappingUpdate,
  AutocountMappingView,
  AutocountMappingWriteRow,
  AutocountPreviewResult,
  AutocountSimulateFieldResult,
  AutocountSimulateResult,
  AutocountSinkTargetInput,
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
 * Two connections: a healthy MSSQL source and a PostgreSQL one whose schema
 * fetch FAILS - so the editor's connection-error state is reachable by a real
 * click (switch the connection picker), no backend needed.
 */
const SQL_CONNECTIONS: AutocountSqlConnection[] = [
  {
    id: 'conn-sql-1',
    name: 'AutoCount SQL Server',
    dialect: 'mssql',
    database: 'AED_Sorento_2024',
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

/** Draft defaults for a never-configured entity (documents get a from-date). */
function defaultEtlConfig(entityType: string): AutocountEtlSourceConfig {
  return {
    connectionId: SQL_CONNECTIONS[0].id,
    query: '',
    lineQuery: isDocumentEntity(entityType) ? '' : null,
    keyColumns: [],
    watermarkColumn: null,
    comparedColumns: [],
    fromDate: isDocumentEntity(entityType) ? '2026-08-30' : null,
    incrementalMinutes: 5,
    reconcileMode: 'dailyAt',
    reconcileHours: null,
    reconcileAt: '02:00',
  };
}

/** In-memory task store so draft saves round-trip within the session. */
const etlTasks = new Map<string, AutocountEtlTask>();

function etlTaskFor(companyId: string, entityType: string): AutocountEtlTask {
  const key = `${companyId}:${entityType}`;
  const existing = etlTasks.get(key);
  if (existing) return existing;
  const task: AutocountEtlTask = {
    companyId,
    entityType,
    etlStatus: 'draft',
    activatedAt: null,
    sourceConfig: defaultEtlConfig(entityType),
    resultColumns: [],
    lastPreviewAt: null,
    lastRunAt: null,
    lastRunError: null,
    lastRunErrorCode: null,
    nextIncrementalAt: null,
    nextReconcileAt: null,
  };
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

/** Lay the session's lifecycle state over a (real or mock) task. */
function applyTaskOverlay(task: AutocountEtlTask): AutocountEtlTask {
  const o = overlayFor(task.companyId, task.entityType);
  return {
    ...task,
    ...o,
    sourceConfig: task.sourceConfig,
    ...nextRunsFor(o.etlStatus, task.sourceConfig),
  };
}

/** The columns a saved query yields - from the session's preview of it, else
 * the saved picks (so an existing task still lists something to map). */
function resultColumnsFor(cfg: AutocountEtlSourceConfig): string[] {
  const seen = previewColumnsByQuery.get(normalizeQuery(cfg.query));
  if (seen) return [...seen];
  const picks = [...cfg.keyColumns, ...(cfg.watermarkColumn ? [cfg.watermarkColumn] : []), ...cfg.comparedColumns];
  return Array.from(new Set(picks));
}

/** A config save supersedes any earlier preview (the gate must re-run). */
function noteTaskSaved(companyId: string, entityType: string, cfg: AutocountEtlSourceConfig): void {
  const o = overlayFor(companyId, entityType);
  o.resultColumns = resultColumnsFor(cfg);
  o.lastPreviewAt = null;
}

/**
 * The pure mock's company: a `*legacy*` id models a row that delivered to
 * Sorento BEFORE the company code existed (backfilled NULL) - the only way a
 * sorento sink with a blank code can exist, since the save guard refuses it.
 */
function mockCompanyState(id: string): AutocountCompany {
  const legacy = id.includes('legacy');
  const sink = mockSinks.get(id);
  return mockCompany({
    id,
    sinkImpl: sink?.sinkImpl ?? (legacy ? 'sorento' : 'logging'),
    sinkConnectionId: sink?.sinkConnectionId ?? (legacy ? 'conn-9' : null),
  });
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
  if (!task.sourceConfig.query.trim() || task.sourceConfig.keyColumns.length === 0) {
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

/** Test seam: forget every S2 session state (the Vitest suite isolates cases). */
export function resetEtlMockState(): void {
  etlOverlays.clear();
  companyCodes.clear();
  mockSinks.clear();
  sourceImpls.clear();
  previewColumnsByQuery.clear();
  etlRuns.clear();
  etlTasks.clear();
}

export const mockAutocountService: AutocountService = {
  listCompanies(): Promise<ListResult<AutocountCompany>> {
    return Promise.resolve({ data: [mockCompany()], total: 1, page: 0 });
  },

  getCompany(id: string): Promise<AutocountCompanyDetail> {
    return Promise.resolve(
      applyDetailOverlay({
        company: mockCompanyState(id),
        entities: [
          {
            id: `${id}-customer`,
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
          },
        ],
      }),
    );
  },

  createCompany(): Promise<AutocountCompany> {
    return Promise.resolve(mockCompany());
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

  getMapping(_companyId: string, entityType: string): Promise<AutocountMappingView> {
    return Promise.resolve(mockMappingView(entityType));
  },

  updateMapping(
    _companyId: string,
    entityType: string,
    input: AutocountMappingUpdate,
  ): Promise<AutocountMappingView> {
    // A required Sorento target left unmapped is the real failure the editor
    // guards; a target outside the accepted set is a 422 server-side. The mock
    // rejects an unknown target so the surfaced-error path is testable.
    const view = mockMappingView(entityType);
    const accepted = new Set(view.sorentoFields.map((f) => f.field));
    for (const row of input.rows) {
      if (!accepted.has(row.sorentoField)) {
        return Promise.reject(
          new ApiError(
            `'${row.sorentoField}' is not a Sorento field accepted for ${entityType}.`,
            422,
          ),
        );
      }
    }
    return Promise.resolve({
      ...view,
      rows: input.rows.map((row) => ({
        sourcePath: row.sourcePath,
        transform: row.transform,
        formula: row.formula?.trim() ? row.formula.trim() : null,
        sorentoField: row.sorentoField,
        canonicalField: row.sorentoField,
        scope: 'header',
        isRequired: view.sorentoFields.find((f) => f.field === row.sorentoField)?.required ?? false,
        isEnabled: true,
      })),
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
    _companyId: string,
    entityType: string,
    record: Record<string, unknown>,
    rows?: AutocountMappingWriteRow[],
  ): Promise<AutocountSimulateResult> {
    // A light stand-in for the real MappingEngine: evaluate each draft (or saved)
    // deliverable row's formula/passthrough over the flat mock record so the
    // record-in → record-out preview + per-field errors are tunable with no
    // backend. The real engine is authoritative; this only drives the UI states.
    const view = mockMappingView(entityType);
    const source = rows
      ? rows.map((r) => ({
          sourcePath: r.sourcePath,
          formula: r.formula ?? null,
          canonicalField: r.sorentoField,
        }))
      : view.rows
          .filter((r) => r.sorentoField)
          .map((r) => ({
            sourcePath: r.sourcePath,
            formula: r.formula,
            canonicalField: r.sorentoField as string,
          }));

    const headerFields: AutocountSimulateFieldResult[] = [];
    const out: Record<string, unknown> = {};
    let ok = true;
    for (const r of source) {
      const raw = record[r.sourcePath];
      const present = raw !== undefined;
      const formula = r.formula?.trim() ? r.formula.trim() : 'value';
      const evaluated = present
        ? evalFormula(formula, raw)
        : { ok: true, output: null, error: null };
      if (!evaluated.ok) ok = false;
      if (evaluated.ok && present) out[r.canonicalField] = evaluated.output;
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

    return Promise.resolve({
      ok,
      sourceRef: String(record.AccNo ?? record.DocNo ?? ''),
      docNo: (record.DocNo as string | undefined) ?? null,
      record: ok ? out : null,
      headerFields,
      lineFields: [],
      errors: ok
        ? []
        : headerFields.filter((f) => !f.ok).map((f) => ({ field: f.canonicalField, message: f.error })),
    });
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

  async previewSqlQuery(
    connectionId: string,
    query: string,
  ): Promise<AutocountSqlPreview> {
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
    const cfg = input.sourceConfig;
    // Mirrors the save-time guard (AC-22-11): documents need a from-date.
    if (isDocumentEntity(entityType) && !cfg.fromDate) {
      throw new ApiError('From date is required for documents.', 422, null, {
        fieldErrors: { fromDate: 'From date is required for documents.' },
      });
    }
    const next: AutocountEtlTask = {
      ...current,
      sourceConfig: cloneJson(cfg),
    };
    etlTasks.set(`${companyId}:${entityType}`, next);
    noteTaskSaved(companyId, entityType, cfg);
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
};

/**
 * PHASE 1 MOCK OVERLAY (plan 22 S2). Wraps the REAL service so the S1
 * endpoints keep serving real data while the S2 additions (lifecycle, preview,
 * runs, `sourceImpl`, `sorentoCompanyCode`, the task's new read-only fields)
 * come from this session's in-memory state. The real backend ignores the
 * extra request fields it does not know yet; this overlay remembers them and
 * lays them back over the real responses. Phase 2 deletes this binding.
 */
export function withPhase1EtlMock(real: AutocountService): AutocountService {
  const overlaid: AutocountService = {
    ...real,

    async getCompany(id) {
      return applyDetailOverlay(await real.getCompany(id));
    },

    async updateSinkTarget(companyId, input) {
      guardSinkTarget(input);
      const saved = await real.updateSinkTarget(companyId, input);
      noteSinkTarget(companyId, input);
      return applyCompanyOverlay(saved);
    },

    async updateEntityConfig(companyId, entityType, input) {
      const { sourceImpl, ...rest } = input;
      if (sourceImpl && sourceImpl !== 'autocount_read' && sourceImpl !== 'sql_db') {
        throw new ApiError('Unknown source.', 422);
      }
      const saved = await real.updateEntityConfig(companyId, entityType, rest);
      if (sourceImpl) noteSourceImpl(companyId, entityType, sourceImpl);
      return applyEntityOverlay(companyId, saved);
    },

    async previewSqlQuery(connectionId, query) {
      const preview = await real.previewSqlQuery(connectionId, query);
      previewColumnsByQuery.set(normalizeQuery(query), preview.columns.map((c) => c.name));
      return preview;
    },

    async getEtlTask(companyId, entityType) {
      const task = await real.getEtlTask(companyId, entityType);
      const o = overlayFor(companyId, entityType);
      if (o.resultColumns.length === 0) o.resultColumns = resultColumnsFor(task.sourceConfig);
      return applyTaskOverlay(task);
    },

    async updateEtlTask(companyId, entityType, input) {
      const saved = await real.updateEtlTask(companyId, entityType, input);
      noteTaskSaved(companyId, entityType, saved.sourceConfig);
      return applyTaskOverlay(saved);
    },

    async previewEtlTask(companyId, entityType) {
      const [detail, task] = await Promise.all([
        overlaid.getCompany(companyId),
        overlaid.getEtlTask(companyId, entityType),
      ]);
      return mockPreviewEtlTask(detail.company, task);
    },

    async activateEtlTask(companyId, entityType) {
      await pause(200);
      const [detail, task] = await Promise.all([
        overlaid.getCompany(companyId),
        overlaid.getEtlTask(companyId, entityType),
      ]);
      return mockActivate(detail.company, task);
    },

    async pauseEtlTask(companyId, entityType) {
      await pause(250);
      return mockPause(await overlaid.getEtlTask(companyId, entityType));
    },

    async resumeEtlTask(companyId, entityType) {
      await pause(250);
      return mockResume(await overlaid.getEtlTask(companyId, entityType));
    },

    async runEtlTaskNow(companyId, entityType) {
      await pause(500);
      const [detail, task] = await Promise.all([
        overlaid.getCompany(companyId),
        overlaid.getEtlTask(companyId, entityType),
      ]);
      return mockRunNow(detail.company, task);
    },

    async listEtlRuns(companyId, entityType, query) {
      await pause(200);
      return mockListEtlRuns(companyId, entityType, query);
    },
  };
  return overlaid;
}

/** A realistic supplier/customer mapping view for the editor's tunable states. */
function mockMappingView(entityType: string): AutocountMappingView {
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
  };
}
