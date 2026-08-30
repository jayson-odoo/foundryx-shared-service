/**
 * Direct-DB ETL helpers (plan 22, slice S1) - pure, shared by the task
 * editor, the SQL editor and the mock service. No React, no fetch.
 */
import type {
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
