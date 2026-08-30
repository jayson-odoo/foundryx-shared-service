/**
 * Direct-DB ETL helpers (plan 22, slice S1) - pure, shared by the task
 * editor, the SQL editor and the mock service. No React, no fetch.
 */
import type {
  AutocountAnchorErrorCode,
  AutocountCompany,
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
