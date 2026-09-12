/**
 * Direct-DB ETL helpers (plan 22, slice S1) - pure, shared by the task
 * editor, the SQL editor and the mock service. No React, no fetch.
 */
import type {
  AutocountAnchorErrorCode,
  AutocountCompany,
  AutocountEntityConfig,
  AutocountEtlSourceConfig,
  AutocountEtlTask,
  AutocountEtlTaskError,
  AutocountSqlPreview,
  AutocountSqlSchema,
  HttpPreview,
} from '@/types/autocount';

/**
 * Entities whose task carries a second (line) query + a from-date (Q20).
 * `shipping_order` (sprint-5/02, AC-02-10) is a document entity too, ahead of
 * its own backend registration (S3) - this list is FE-internal presentation
 * routing only, NOT the "Add entity" picker's candidate list (that stays
 * `AC_SQL_DB_ENTITY_TYPES`/`AC_NEW_MASTER_ENTITY_TYPES` in `autocount-meta.ts`,
 * parity-pinned to the backend registry - do not add `shipping_order` there
 * until S3 lands it server-side).
 */
const DOCUMENT_ENTITY_TYPES = new Set(['sales_order', 'purchase_order', 'shipping_order']);

/** True for header+lines document entities (SO/PO). Code constants, never a
 * tenant-editable key. */
export function isDocumentEntity(entityType: string): boolean {
  return DOCUMENT_ENTITY_TYPES.has(entityType);
}

/** Display label per dialect (the only three the provider offers). */
export const SQL_DIALECT_LABELS: Record<string, string> = {
  mssql: 'Microsoft SQL Server',
  postgresql: 'PostgreSQL',
  mysql: 'MySQL',
};

/**
 * Options for the key/watermark/compared pickers: the preview's result
 * columns, plus any SAVED picks the current preview no longer returns (so an
 * existing task renders its stored selection instead of silently dropping it -
 * the save-time guard is the backend's, AC-22-11).
 */
export function pickerColumnOptions(
  previewColumns: string[],
  saved: string[],
): string[] {
  const seen = new Set(previewColumns);
  const stale = saved.filter((c) => !seen.has(c));
  return [...previewColumns, ...stale];
}

/** The result badge: row count, cap marker, duration. */
export function previewBadgeText(preview: AutocountSqlPreview): string {
  const rows = `${preview.rowCount} row${preview.rowCount === 1 ? '' : 's'}`;
  const cap = preview.truncated ? ' (first 100)' : '';
  const secs = (preview.durationMs / 1000).toFixed(2);
  return `${rows}${cap} · ${secs} s`;
}

/**
 * The introspected tree as CodeMirror lang-sql completion config:
 * `{"<schema>.<table>": [columns]}` keyed with the schema prefix, plus the
 * first schema as `defaultSchema` so bare table names complete too.
 */
export function schemaCompletionConfig(schema: AutocountSqlSchema | null): {
  schema: Record<string, string[]>;
  defaultSchema?: string;
} {
  if (!schema) return { schema: {} };
  const tables: Record<string, string[]> = {};
  for (const node of schema.schemas) {
    for (const table of node.tables) {
      tables[`${node.name}.${table.name}`] = table.columns.map((c) => c.name);
    }
  }
  return { schema: tables, defaultSchema: schema.schemas[0]?.name };
}

/** The starter statement a schema-tree table action inserts (AC-22-07). */
export function starterQuery(schemaName: string, tableName: string): string {
  return `SELECT * FROM ${schemaName}.${tableName}`;
}

/** Today as the wire's `fromDate` (YYYY-MM-DD - a date, not a datetime). */
export function todayDateString(): string {
  const now = new Date();
  const month = String(now.getMonth() + 1).padStart(2, '0');
  const day = String(now.getDate()).padStart(2, '0');
  return `${now.getFullYear()}-${month}-${day}`;
}

// ── plan 22 S2 - activation gate, anchor errors, run cost ────────────────────

/** Why Activate / Run preview is withheld (foolproof-UI: stated, never silent). */
export type EtlPrerequisiteKind = 'company' | 'companyCode' | 'query' | 'keys' | 'unsaved';

export interface EtlPrerequisite {
  kind: EtlPrerequisiteKind;
  message: string;
}

/**
 * The prerequisite warnings the Review & Activate tab shows in place of a
 * guaranteed-to-fail Run preview / Activate (AC-22-18). Order = the order an
 * operator fixes them: company delivery first, then the task itself.
 */
export function activatePrerequisites(input: {
  company: AutocountCompany | null;
  task: AutocountEtlTask;
  configDirty: boolean;
}): EtlPrerequisite[] {
  const { company, task, configDirty } = input;
  const out: EtlPrerequisite[] = [];
  if (!company) {
    out.push({ kind: 'company', message: 'Company details are still loading.' });
  } else if (company.sinkImpl === 'sorento' && !(company.sorentoCompanyCode ?? '').trim()) {
    // sprint-5/08 review round 4 - the logging sink is a legitimate
    // configured default (`CompanyService.sink_for_company`), not an
    // unfinished setup: it needs no company code (`set_sink_target` clears
    // it on that switch) and the server anchor gate
    // (`EtlService.activate_task`) only ever requires one for the Sorento
    // sink. Blocking Activate here for a logging-sink company made the
    // AC's own "Activate -> Run now with the logging sink" precondition
    // unreachable through the real UI.
    out.push({ kind: 'companyCode', message: 'This company has no Sorento company code.' });
  }
  // sprint-5/08 D13 - an `autocount_http` task never has a `query`/
  // `keyColumns` (only `path`/`keyFields`); check whichever pair the task's
  // OWN impl actually uses, never the SQL-only fields unconditionally.
  const isHttp = task.sourceImpl === 'autocount_http';
  const configured = isHttp ? Boolean(task.sourceConfig.path?.trim()) : task.sourceConfig.query.trim();
  const keysPicked = isHttp
    ? (task.sourceConfig.keyFields?.length ?? 0) > 0
    : task.sourceConfig.keyColumns.length > 0;
  if (configDirty) {
    out.push({ kind: 'unsaved', message: 'Save the task first.' });
  } else if (!configured) {
    out.push({ kind: 'query', message: isHttp ? 'No endpoint saved yet.' : 'No query saved yet.' });
  } else if (!keysPicked) {
    out.push({ kind: 'keys', message: 'No key columns picked yet.' });
  }
  return out;
}

/**
 * Whether the last preview's genuinely-FAILED rows block Activate (S5 review
 * SHOULD-FIX 4b - mirrors `EtlService.activate_task`'s server gate). Kept
 * SEPARATE from `activatePrerequisites` on purpose: those also gate Run
 * preview, and the fix for a failed preview IS re-running preview after
 * editing the mapping - blocking that button would trap the operator with
 * no way out. `retryable` rows never trip this (a dependency-order
 * carry-over, AC-22-23, resolves itself on a later run).
 */
export function previewFailedBlocksActivation(
  task: Pick<AutocountEtlTask, 'lastPreviewFailedCount'>,
): boolean {
  return Boolean(task.lastPreviewFailedCount);
}

// ── plan 22 S4 - dependency-order heads-up (AC-22-23) ────────────────────────
// A `product` task can be activated with no category/UOM task active - the
// mechanism (retryable stays staged, re-offered next run) makes this SAFE, so
// this is a WARNING chip, never a block (foolproof-UI: warn on missing
// prerequisites, don't refuse a valid action). Derived from the company's
// ALREADY-FETCHED entity list - no extra request.
const PRODUCT_DEPENDENCIES: { entityType: string; label: string }[] = [
  { entityType: 'product_category', label: 'category' },
  { entityType: 'unit_of_measure', label: 'unit of measure' },
];

/**
 * Foolproof-UI (sprint-5/08 review round 5) - the ONE signal a logging-sink
 * company delivers nowhere. Round 4 correctly dropped the `'sink'`
 * PREREQUISITE (a logging sink is a legitimate configured default, not an
 * unfinished setup - it must not block Activate/Run now), but that also
 * deleted the operator's only heads-up that runs land in the log only. A
 * NON-blocking warning, same shape as `productDependencyWarning`: it never
 * withholds Activate, it only states the fact plainly. `null` once a
 * company is still loading (nothing to warn about yet) or already points
 * at Sorento.
 */
export function loggingSinkWarning(
  company: Pick<AutocountCompany, 'sinkImpl'> | null,
): string | null {
  if (!company || company.sinkImpl !== 'logging') return null;
  return 'Runs on this company are logged only - no records are delivered until a Sorento target is set.';
}

/**
 * Non-null only for a `product` task whose company has no ACTIVE category
 * and/or unit-of-measure task yet - such a product lands `retryable` on
 * Sorento until that dependency syncs (AC-22-23), which resolves on its own
 * on the next run once it does.
 */
export function productDependencyWarning(
  entityType: string,
  entities: Pick<AutocountEntityConfig, 'entityType' | 'etlStatus'>[],
): string | null {
  if (entityType !== 'product') return null;
  const missing = PRODUCT_DEPENDENCIES.some(
    (dep) => !entities.some((e) => e.entityType === dep.entityType && e.etlStatus === 'active'),
  );
  if (!missing) return null;
  return 'No active category or unit-of-measure task yet - products may not sync until one runs.';
}

/**
 * The Review & Activate banner for a `brand` task whose consumer contract
 * does not yet accept brands (sprint-5/08, AC-08-33) - a WARNING, never a
 * block: the task still activates and runs, it simply falls back to the
 * logging sink for `brand` until the consumer deploys the entity. `null`
 * once `task.brandContractGate` is absent (every non-brand task, and a
 * brand task the consumer already accepts).
 */
export function brandContractBanner(
  task: Pick<AutocountEtlTask, 'brandContractGate'>,
): string | null {
  const gate = task.brandContractGate;
  if (!gate) return null;
  const version = gate.version ?? 'unknown';
  return `Consumer contract ${version} - brands land when ${gate.requiredVersion} is deployed`;
}

const ANCHOR_TITLES: Record<AutocountAnchorErrorCode, string> = {
  COMPANY_ANCHOR_REQUIRED: 'Sorento company code required',
  UNKNOWN_COMPANY: 'Unknown Sorento company',
  COMPANY_ANCHOR_AMBIGUOUS: 'Sorento company code is ambiguous',
  // The integration's OWN company binding is broken (Appendix A6's fourth
  // code) - never attributed to a record, and not something re-entering the
  // company code alone necessarily fixes (S2 review SHOULD-FIX 8).
  COMPANY_BINDING_INVALID: 'Sorento company binding is invalid',
};

/** True for one of Sorento's four company-anchor codes (Appendix A6). */
export function isAnchorErrorCode(code: string | null | undefined): code is AutocountAnchorErrorCode {
  return Boolean(code) && Object.prototype.hasOwnProperty.call(ANCHOR_TITLES, code as string);
}

/** The alert title for a task-level error code. */
export function anchorErrorTitle(code: string | null | undefined): string {
  return isAnchorErrorCode(code) ? ANCHOR_TITLES[code] : 'Task error';
}

/**
 * Read a 422's `{fieldErrors: {field: message}}` detail into a flat map
 * (empty when the detail carries none) - the per-field shape the task save
 * (AC-22-11) and the company create (AC-01-14) both return.
 */
export function readFieldErrors(detail: unknown): Record<string, string> {
  if (!detail || typeof detail !== 'object') return {};
  const bag = (detail as { fieldErrors?: unknown }).fieldErrors;
  if (!bag || typeof bag !== 'object') return {};
  const out: Record<string, string> = {};
  for (const [key, value] of Object.entries(bag as Record<string, unknown>)) {
    if (typeof value === 'string') out[key] = value;
  }
  return out;
}

/** Read the structured `{code, message}` detail of a task-level 422; null otherwise. */
export function readTaskError(detail: unknown): AutocountEtlTaskError | null {
  if (!detail || typeof detail !== 'object') return null;
  const bag = detail as { code?: unknown; message?: unknown };
  if (typeof bag.code !== 'string' || typeof bag.message !== 'string') return null;
  return { code: bag.code, message: bag.message };
}

/** Run duration for the history list (cost per run, AC-22-17). */
export function formatDurationMs(ms: number | null | undefined): string {
  if (ms === null || ms === undefined || !Number.isFinite(ms)) return '-';
  if (ms < 60_000) return `${(ms / 1000).toFixed(1)} s`;
  const minutes = Math.floor(ms / 60_000);
  const seconds = Math.round((ms % 60_000) / 1000);
  return `${minutes} min ${seconds} s`;
}

/**
 * The Mapping tab's source-column picker for a DB task (AC-22-09): the saved
 * query's result columns, plus the columns of a preview run in THIS session
 * (an unsaved query edit), plus whatever the existing rows already reference
 * (so a stored mapping renders instead of silently blanking). Order-preserving,
 * de-duplicated.
 */
// ── plan 22 S3 - schedule (AC-22-12) ─────────────────────────────────────────
//
// Mirrors the backend's own floors/format exactly (`etl_service.py`
// `validate_source_config`/`next_run_times`) so the tab's live feedback never
// diverges from the save-time 422 the server is authoritative for.

/** Incremental floor with a watermark column (AC-22-12). */
export const MIN_INCREMENTAL_MINUTES = 1;
/** Incremental floor WITHOUT one - the task runs hash-diff as its incremental. */
export const MIN_INCREMENTAL_MINUTES_NO_WATERMARK = 15;
/** Reconcile "every N hours" floor. */
export const MIN_RECONCILE_HOURS = 1;

export const RECONCILE_TIME_RE = /^([01]\d|2[0-3]):[0-5]\d$/;

/** The incremental floor for a task (AC-22-12): 1 minute with a watermark
 * column, 15 without (hash-diff incremental). */
export function incrementalFloorMinutes(hasWatermark: boolean): number {
  return hasWatermark ? MIN_INCREMENTAL_MINUTES : MIN_INCREMENTAL_MINUTES_NO_WATERMARK;
}

/** Live mirror of the save-time floor guard - the server re-validates on
 * save regardless (422 `fieldErrors.incrementalMinutes`). */
export function validateIncrementalMinutes(
  minutes: number | null | undefined,
  hasWatermark: boolean,
): string | null {
  const floor = incrementalFloorMinutes(hasWatermark);
  if (minutes === null || minutes === undefined || !Number.isFinite(minutes)) {
    return 'Enter the incremental interval in minutes.';
  }
  if (minutes < floor) {
    return hasWatermark
      ? `At least ${floor} minute.`
      : `At least ${floor} minutes without a watermark column.`;
  }
  return null;
}

/** Live mirror of the reconcile "every N hours" floor guard. */
export function validateReconcileHours(hours: number | null | undefined): string | null {
  if (hours === null || hours === undefined || !Number.isFinite(hours)) {
    return 'Enter the reconcile interval in hours.';
  }
  if (hours < MIN_RECONCILE_HOURS) return `At least ${MIN_RECONCILE_HOURS} hour.`;
  return null;
}

/** Live mirror of the daily-at HH:MM format guard. */
export function validateReconcileAt(value: string | null | undefined): string | null {
  if (!value || !RECONCILE_TIME_RE.test(value)) {
    return 'Enter the daily reconcile time as HH:MM.';
  }
  return null;
}

/** The reconcile-mode picker's ONLY two options (foolproof-UI). */
export const RECONCILE_MODE_OPTIONS: { label: string; value: AutocountEtlSourceConfig['reconcileMode'] }[] = [
  { label: 'Daily at', value: 'dailyAt' },
  { label: 'Every N hours', value: 'interval' },
];

export function mappingSourceColumns(
  resultColumns: string[],
  previewColumns: string[],
  mappedPaths: string[],
): string[] {
  const seen = new Set<string>();
  const out: string[] = [];
  for (const name of [...resultColumns, ...previewColumns, ...mappedPaths]) {
    if (!name || seen.has(name)) continue;
    seen.add(name);
    out.push(name);
  }
  return out;
}

// ── plan 22 S5 review SHOULD-FIX 4c - a `status` seed formula, VALUE not copy ─

/**
 * A document's `status` target has a fixed 5-word vocabulary server-side
 * (open/partial/fulfilled/closed/cancelled) - AutoCount's real-world shape is
 * usually a boolean flag (`IsCancelled`/`IsClosed`), so a mapping row that
 * targets `status` on a boolean-typed SOURCE column gets an EDITABLE starting
 * formula pre-filled rather than an operator hand-writing it from nothing.
 *
 * A VALUE pre-fill, never on-screen instructional copy (foolproof-UI, user
 * mandate): the row's `formula` field is populated with what would actually
 * be SAVED, editable like any other formula - not a caption explaining what
 * to type. Never overwrites a formula the operator already set (an existing
 * non-empty formula is left alone); a non-boolean/unknown column type or a
 * non-document entity leaves the formula untouched (empty), never guessed.
 */
export const STATUS_BOOLEAN_SEED_FORMULA = 'if(value == true, "cancelled", "open")';

export function statusFormulaSeed(
  entityType: string,
  sorentoField: string,
  sourceColumnType: string | undefined,
): string | null {
  if (!isDocumentEntity(entityType)) return null;
  if (sorentoField !== 'status') return null;
  if ((sourceColumnType ?? '').toLowerCase() !== 'boolean') return null;
  return STATUS_BOOLEAN_SEED_FORMULA;
}

// ── sprint-5/02 - line aggregates + status vocabulary (AC-02-07/08/20) ───────

/**
 * The five per-header facts the engine computes from a document's MAPPED
 * lines and injects into the header formula scope under the `lines`
 * namespace (AC-02-07). Header formulas run AFTER lines. Shared by the
 * builder's Variables panel and the mock's Simulate aggregate math - keep
 * both in lockstep with `MappingEngine.project_document` when S2 lands it.
 */
export interface LineAggregateDef {
  token: string;
  label: string;
  description: string;
}

export const LINE_AGGREGATES: readonly LineAggregateDef[] = [
  { token: 'lines.count', label: 'Line count', description: 'Every mapped line.' },
  {
    token: 'lines.open_count',
    label: 'Open line count',
    description: 'Lines whose outstanding quantity is greater than zero.',
  },
  { token: 'lines.ordered_sum', label: 'Ordered sum', description: 'Sum of qty_ordered.' },
  {
    token: 'lines.fulfilled_sum',
    label: 'Fulfilled sum',
    description: 'Sum of qty_delivered (SO) / qty_received (PO/SPO).',
  },
  {
    token: 'lines.outstanding_sum',
    label: 'Outstanding sum',
    description: 'Sum of (ordered - fulfilled), floored at 0 per line.',
  },
];

/** The `status` target's fixed output vocabulary (AC-02-08/15) - the ONLY
 * string literals a status formula may return; a formula-builder literal
 * chip set, never a free-typed string on this target. */
export const STATUS_VOCABULARY: readonly string[] = [
  'open',
  'partial',
  'fulfilled',
  'closed',
  'cancelled',
];

/** The default status formula the SO/PO/SPO presets seed (AC-02-08) - never
 * emits `partial` by default (AC-02-15). */
export const DEFAULT_STATUS_FORMULA =
  'if(Cancelled == "T", "cancelled", if(lines.open_count == 0, "closed", "open"))';

// ── open REST API source (sprint-5/08) ────────────────────────────────────────

/**
 * The connect form's default reference-prefix text (AC-08-09): the picked
 * connection's own NAME (never the auth-badged option label), upper-cased,
 * every run of non-alphanumeric characters collapsed to one `_`, trimmed of
 * leading/trailing `_`. Editable afterwards - this only seeds the field.
 */
export function derivePrefix(name: string): string {
  return name
    .toUpperCase()
    .replace(/[^A-Z0-9]+/g, '_')
    .replace(/^_+|_+$/g, '');
}

/** The backend's own format guard (AC-08-07), mirrored client-side so the
 * inline hint / Create-disabled state never round-trips to learn it. */
export const REF_PREFIX_RE = /^[A-Z0-9_]{2,32}$/;

/** One entity's open-API preset (AC-08-16) - path, key/watermark/compared
 * picks, and the "derived from" chip list for a distinct-values entity
 * (`unit_of_measure`). Pure data, no fetch - the Source tab pre-fills a
 * never-configured HTTP task from this the moment "API" + a no-auth
 * connection is picked. */
/** One preset mapping row: a source field -> (transform) -> canonical field,
 * mirroring `AutocountMappingRow` minus the wire-only bookkeeping fields. */
export interface HttpPresetMappingRow {
  sourcePath: string;
  transform: string;
  canonicalField: string;
  required?: boolean;
}

export interface HttpPreset {
  path: string;
  keyFields: string[];
  watermarkField: string | null;
  comparedFields: string[];
  distinctOf: string[] | null;
  /** Seeded on the entity's first clean save (AC-08-16) - the Mapping tab's
   * starting rows, never a constant (the mapping engine has none). */
  mapping: HttpPresetMappingRow[];
}

/**
 * `HTTP_PRESETS` (AC-08-16) - keys pinned to `AC_HTTP_ENTITY_TYPES`
 * (`autocount-meta.ts`); a parity test (S3 backend, `test_autocount_entity_
 * parity.py`) pins this against the server's own `presets.HTTP_PRESETS`.
 *
 * PHASE 1 MOCK ONLY (sprint-5/08 review round 1, NIT) - this table is what a
 * newborn `autocount_http` task's Source tab pre-fills FROM, client-side,
 * before any save (`task-editor-view.tsx`'s "pick API for the first time"
 * and "first mount with no path yet" seeds). The backend now carries the
 * identical data (`modules/autocount/presets.py::HTTP_PRESETS`, exposed via
 * `GET /autocount/presets/{entityType}?companyId=`, S7), so this duplicate
 * copy is a drift risk: a future preset edit (a path change, a new default
 * field) made only on the backend leaves the frontend's OWN pre-fill stale
 * even though the parity test still passes (it checks KEYS, not values).
 * Not swapped in this round - doing so means the Source tab's first-mount
 * effect awaiting a network round trip before it can seed, a behaviour
 * change beyond this round's scope. Tracked for a follow-up: read the
 * preset from `GET /autocount/presets/{entityType}` instead of this local
 * table once that round exists.
 */
export const HTTP_PRESETS: Record<string, HttpPreset> = {
  product: {
    path: '/itembypage',
    keyFields: ['ItemCode'],
    watermarkField: 'LastModified',
    comparedFields: [],
    distinctOf: null,
    mapping: [
      { sourcePath: 'ItemCode', transform: 'string', canonicalField: 'code', required: true },
      { sourcePath: 'Description', transform: 'string', canonicalField: 'name', required: true },
      { sourcePath: 'Desc2', transform: 'string', canonicalField: 'description' },
      { sourcePath: 'ItemGroup', transform: 'string', canonicalField: 'category_code' },
      { sourcePath: 'ItemBrand', transform: 'string', canonicalField: 'brand_code' },
      { sourcePath: 'BaseUOM', transform: 'string', canonicalField: 'uom_code' },
      { sourcePath: 'IsActive', transform: 't_f_bool', canonicalField: 'is_active', required: true },
      { sourcePath: 'Discontinued', transform: 't_f_bool', canonicalField: 'is_discontinued' },
    ],
  },
  customer: {
    path: '/debtorbypage',
    keyFields: ['AccNo'],
    watermarkField: 'LastModified',
    comparedFields: [],
    distinctOf: null,
    mapping: [
      { sourcePath: 'AccNo', transform: 'string', canonicalField: 'code', required: true },
      { sourcePath: 'CompanyName', transform: 'string', canonicalField: 'name', required: true },
      { sourcePath: 'Phone1', transform: 'string', canonicalField: 'phone_number' },
      { sourcePath: 'IsActive', transform: 't_f_bool', canonicalField: 'is_active', required: true },
    ],
  },
  warehouse: {
    path: '/location',
    keyFields: ['Location'],
    watermarkField: null,
    comparedFields: [],
    distinctOf: null,
    mapping: [
      { sourcePath: 'Location', transform: 'string', canonicalField: 'code', required: true },
      { sourcePath: 'Description', transform: 'string', canonicalField: 'name', required: true },
      { sourcePath: 'Address1', transform: 'string', canonicalField: 'location' },
      { sourcePath: 'IsActive', transform: 't_f_bool', canonicalField: 'is_active', required: true },
    ],
  },
  product_category: {
    path: '/ItemGroup',
    keyFields: ['ItemGroup'],
    watermarkField: null,
    comparedFields: [],
    distinctOf: null,
    mapping: [
      { sourcePath: 'ItemGroup', transform: 'string', canonicalField: 'code', required: true },
      { sourcePath: 'Description', transform: 'string', canonicalField: 'name', required: true },
      { sourcePath: 'Desc2', transform: 'string', canonicalField: 'description' },
    ],
  },
  brand: {
    path: '/ItemBrand',
    keyFields: ['ItemBrand'],
    watermarkField: null,
    comparedFields: [],
    distinctOf: null,
    mapping: [
      { sourcePath: 'ItemBrand', transform: 'string', canonicalField: 'code', required: true },
      { sourcePath: 'ItemBrand', transform: 'string', canonicalField: 'name', required: true },
      { sourcePath: 'Description', transform: 'string', canonicalField: 'description' },
    ],
  },
  unit_of_measure: {
    path: '/itembypage',
    keyFields: ['value'],
    watermarkField: null,
    comparedFields: [],
    distinctOf: ['BaseUOM', 'SalesUOM', 'PurchaseUOM'],
    mapping: [
      { sourcePath: 'value', transform: 'string', canonicalField: 'code', required: true },
      { sourcePath: 'value', transform: 'string', canonicalField: 'name', required: true },
    ],
  },
};

/**
 * The HTTP preview's envelope badge (D14): "a run walks every page" is
 * spelled out for a paged envelope so the page-count is never a mystery
 * number; a list envelope states it is one request.
 */
export function httpPreviewBadgeText(preview: HttpPreview): string {
  if (preview.envelope === 'list') {
    const rows = preview.rows.length;
    return `List · ${rows} row${rows === 1 ? '' : 's'} · one request`;
  }
  const total = preview.totalCount ?? 0;
  const pages = Math.max(1, Math.ceil(total / 1000));
  return `Paged · ${total.toLocaleString('en-US')} total · ${pages} page${pages === 1 ? '' : 's'} of 1000 - a run walks every page`;
}

/**
 * Adapts an `HttpPreview` into the SAME shape `SqlPreviewGrid` already
 * renders (AC-08-19: "reuse SqlPreviewGrid", never a parallel grid) - a
 * column's SAMPLE value stands in for the SQL grid's reported TYPE (the open
 * API carries no schema at all), and every row/duration passes through
 * untouched.
 */
export function httpPreviewAsSqlPreview(preview: HttpPreview): AutocountSqlPreview {
  return {
    columns: preview.columns.map((c) => ({
      name: c.name,
      type: c.sample === null || c.sample === undefined ? '' : String(c.sample),
    })),
    rows: preview.rows,
    rowCount: preview.rows.length,
    truncated: false,
    durationMs: preview.durationMs,
  };
}
