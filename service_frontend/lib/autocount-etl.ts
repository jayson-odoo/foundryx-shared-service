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
} from '@/types/autocount';

/** Entities whose task carries a second (line) query + a from-date (Q20). */
const DOCUMENT_ENTITY_TYPES = new Set(['sales_order', 'purchase_order']);

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
export type EtlPrerequisiteKind = 'company' | 'sink' | 'companyCode' | 'query' | 'keys' | 'unsaved';

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
  } else if (company.sinkImpl !== 'sorento') {
    out.push({ kind: 'sink', message: 'This company has no delivery target (logging only).' });
  } else if (!(company.sorentoCompanyCode ?? '').trim()) {
    out.push({ kind: 'companyCode', message: 'This company has no Sorento company code.' });
  }
  if (configDirty) {
    out.push({ kind: 'unsaved', message: 'Save the task first.' });
  } else if (!task.sourceConfig.query.trim()) {
    out.push({ kind: 'query', message: 'No query saved yet.' });
  } else if (task.sourceConfig.keyColumns.length === 0) {
    out.push({ kind: 'keys', message: 'No key columns picked yet.' });
  }
  return out;
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
  const missing = PRODUCT_DEPENDENCIES.filter(
    (dep) => !entities.some((e) => e.entityType === dep.entityType && e.etlStatus === 'active'),
  );
  if (missing.length === 0) return null;
  const names = missing.map((d) => d.label).join(' and ');
  return `No active ${names} task on this company yet - this product may land retryable until it does.`;
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

/** True for one of Sorento's three company-anchor codes (Appendix A6). */
export function isAnchorErrorCode(code: string | null | undefined): code is AutocountAnchorErrorCode {
  return Boolean(code) && Object.prototype.hasOwnProperty.call(ANCHOR_TITLES, code as string);
}

/** The alert title for a task-level error code. */
export function anchorErrorTitle(code: string | null | undefined): string {
  return isAnchorErrorCode(code) ? ANCHOR_TITLES[code] : 'Task error';
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
