'use client';

import { ArrowRight, FunctionSquare, Plus, Trash2 } from 'lucide-react';
import { type ColumnDef, getCoreRowModel, useReactTable } from '@tanstack/react-table';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import { DataGrid } from '@/components/ui/data-grid';
import { DataGridTable } from '@/components/ui/data-grid-table';
import { SearchSelect } from '@/components/platform/search-select';
import { ClampedText } from '@/components/platform/clamped-text';
import { humanizeFieldKey } from '@/lib/autocount-diff';
import { statusFormulaSeed } from '@/lib/autocount-etl';
import type {
  AutocountMappingRow,
  AutocountSorentoField,
} from '@/types/autocount';
import {
  AC_PRESET_OPTIONS,
  applyPreset,
  presetForRow,
  presetOptionsForField,
} from '../../../../../../components/autocount-meta';

/** One deliverable mapping row in the editor's working state. */
export interface MappingEditableRow {
  sourcePath: string;
  transform: string;
  /** The row's safe transform formula (slice 16). NULL ⇒ the named `transform`
   *  runs (exact); a non-empty formula is authoritative. */
  formula: string | null;
  sorentoField: string;
}

/** The preset label a row currently reflects (read-mode display). */
function presetLabel(row: MappingEditableRow): string {
  const key = presetForRow(row.transform, row.formula);
  return AC_PRESET_OPTIONS.find((o) => o.value === key)?.label ?? key;
}

/** The Sorento field shown by its human label; the stored name stays the key. */
export function sorentoFieldLabel(field: string): string {
  return humanizeFieldKey(field);
}

/**
 * The required Sorento fields (`code`, `name`, `is_active`) with no source row
 * mapping them - the exact null-record failure a sync would hit. Warned before
 * save, never silently allowed (AC-15-44). Pure, so it is unit-tested directly.
 */
export function unmappedRequiredFields(
  rows: MappingEditableRow[],
  sorentoFields: AutocountSorentoField[],
): string[] {
  const mapped = new Set(rows.map((r) => r.sorentoField).filter(Boolean));
  return sorentoFields
    .filter((f) => f.required && !mapped.has(f.field))
    .map((f) => f.field);
}

/**
 * Where a row's source comes from. `path` = the API path's vendor JSON: known
 * paths offered, a free dotted path still allowed. `column` (plan 22 S2,
 * AC-22-09) = a DB task's flat preview result columns and NOTHING else - a
 * typed name that is not a result column would fail every run.
 */
export type MappingSourceMode = 'path' | 'column';

export interface MappingTableProps {
  editing: boolean;
  rows: MappingEditableRow[];
  /** Non-deliverable provenance/identity rows (e.g. last_modified) - read-only. */
  provenanceRows: AutocountMappingRow[];
  /** The ONLY Sorento targets the picker offers (AC-15-42). */
  sorentoFields: AutocountSorentoField[];
  /** Known AutoCount source paths (`path`) or the result columns (`column`). */
  acFields: string[];
  sourceMode?: MappingSourceMode;
  onChangeRow: (index: number, patch: Partial<MappingEditableRow>) => void;
  onAddRow: () => void;
  onRemoveRow: (index: number) => void;
  /** Open the formula builder for a row (AC-16-11). */
  onBuildRow: (index: number) => void;
  /** The task's canonical entity key (drives the `status` seed-formula
   * below, S5 review SHOULD-FIX 4c) - blank on the API-path editor, where
   * a document entity never routes (DB source only). */
  entityType?: string;
  /** Source-column name → reported type (from the current query preview,
   * when one has been run this session) - the SAME vocabulary
   * `describe_type`/`is_orderable_type` use ("boolean", "string", …).
   * Absent/unknown types simply skip the seed - never guessed. */
  columnTypes?: Record<string, string>;
}

/**
 * The AutoCount source → (transform) → Sorento field table (AC-15-40). Read-only
 * by default (plain values); under Edit each cell is a searchable picker. The
 * Sorento picker offers ONLY the accepted set (and never a target already used
 * by another row - a duplicate can't even be selected), so the foolproof-UI
 * guard is enforced in the UI as well as server-side.
 */
export function MappingTable({
  editing,
  rows,
  provenanceRows,
  sorentoFields,
  acFields,
  sourceMode = 'path',
  onChangeRow,
  onAddRow,
  onRemoveRow,
  onBuildRow,
  entityType = '',
  columnTypes = {},
}: MappingTableProps) {
  const columnMode = sourceMode === 'column';
  const sourceOptions = acFields.map((f) => ({ label: f, value: f }));
  const usedTargets = new Set(rows.map((r) => r.sorentoField).filter(Boolean));
  const allTargetsUsed = sorentoFields.every((f) => usedTargets.has(f.field));

  /** Pre-fill the `status` seed formula (S5 review SHOULD-FIX 4c) the moment
   * a row's source+target COMBINE into "a boolean column feeding `status`" -
   * from either edit direction (source picked first, or target picked
   * first). Never overwrites a formula the operator already set. */
  function withStatusSeed(
    row: MappingEditableRow,
    patch: Partial<MappingEditableRow>,
  ): Partial<MappingEditableRow> {
    if (row.formula) return patch;
    const merged = { ...row, ...patch };
    const seed = statusFormulaSeed(entityType, merged.sorentoField, columnTypes[merged.sourcePath]);
    return seed ? { ...patch, formula: seed } : patch;
  }

  // AC-DLA-56 (T7): migrated off the raw <table> onto DataGrid + DataGridTable
  // (sticky header + resizable/movable columns free from DataGrid's own
  // defaults, AC-DLA-13). Columns rebuilt fresh each render (a small,
  // frequently-edited in-memory grid - not worth memoizing against this
  // many closed-over values); `row.index` is the row's position in `rows`,
  // matching the original array index (no sort/filter on this grid).
  const columns: ColumnDef<MappingEditableRow>[] = [
    {
      id: 'source',
      header: columnMode ? 'Source column' : 'AutoCount field',
      cell: ({ row }) => {
        const index = row.index;
        return editing ? (
          <SearchSelect
            options={sourceOptions}
            value={row.original.sourcePath}
            onChange={(value) => onChangeRow(index, withStatusSeed(row.original, { sourcePath: value }))}
            placeholder={
              columnMode
                ? sourceOptions.length > 0
                  ? 'Select a column'
                  : 'No columns yet'
                : 'Select or type a path'
            }
            searchPlaceholder={columnMode ? 'Search columns' : 'Search or type a dotted path'}
            allowCustom={!columnMode}
            disabled={columnMode && sourceOptions.length === 0}
            ariaLabel={`${columnMode ? 'Source column' : 'AutoCount source'} for row ${index + 1}`}
          />
        ) : (
          <code className="text-xs">{row.original.sourcePath}</code>
        );
      },
    },
    {
      id: 'transform',
      header: 'Transform',
      cell: ({ row }) => {
        const index = row.index;
        return editing ? (
          <div className="flex items-center gap-1">
            <div className="min-w-28 flex-1">
              <SearchSelect
                options={presetOptionsForField(row.original.sorentoField)}
                value={presetForRow(row.original.transform, row.original.formula)}
                onChange={(key) => onChangeRow(index, applyPreset(key))}
                ariaLabel={`Transform for row ${index + 1}`}
              />
            </div>
            <Button
              type="button"
              variant="ghost"
              size="sm"
              mode="icon"
              onClick={() => onBuildRow(index)}
              aria-label={`Build formula for row ${index + 1}`}
              title="Edit as a formula"
            >
              <FunctionSquare className="size-4" />
            </Button>
          </div>
        ) : (
          <div className="flex flex-col gap-0.5">
            <span className="text-muted-foreground">{presetLabel(row.original)}</span>
            {row.original.formula && (
              <ClampedText
                text={row.original.formula}
                lines={2}
                className="font-mono text-2xs text-muted-foreground/80"
              />
            )}
          </div>
        );
      },
    },
    {
      id: 'arrow',
      header: () => null,
      cell: () => <ArrowRight className="size-4 text-muted-foreground" />,
      size: 32,
      enableResizing: false,
      enableHiding: false,
      meta: { utility: true },
    },
    {
      id: 'target',
      header: 'Sorento field',
      cell: ({ row }) => {
        const index = row.index;
        // Foolproof: offer this row's own target + any not used elsewhere,
        // so a duplicate target can never be selected.
        const targetOptions = sorentoFields
          .filter((f) => f.field === row.original.sorentoField || !usedTargets.has(f.field))
          .map((f) => ({
            label: f.required ? `${sorentoFieldLabel(f.field)} *` : sorentoFieldLabel(f.field),
            value: f.field,
          }));
        return editing ? (
          <SearchSelect
            options={targetOptions}
            value={row.original.sorentoField}
            onChange={(value) => onChangeRow(index, withStatusSeed(row.original, { sorentoField: value }))}
            placeholder="Select a Sorento field"
            disabled={sorentoFields.length === 0}
            ariaLabel={`Sorento field for row ${index + 1}`}
          />
        ) : (
          <span className="font-medium text-foreground">{sorentoFieldLabel(row.original.sorentoField)}</span>
        );
      },
    },
    ...(editing
      ? [
          {
            id: 'remove',
            header: () => null,
            cell: ({ row }: { row: { index: number } }) => (
              <Button
                type="button"
                variant="ghost"
                size="sm"
                mode="icon"
                onClick={() => onRemoveRow(row.index)}
                aria-label={`Remove row ${row.index + 1}`}
              >
                <Trash2 className="size-4" />
              </Button>
            ),
            size: 44,
            enableResizing: false,
            enableHiding: false,
            meta: { utility: true },
          } satisfies ColumnDef<MappingEditableRow>,
        ]
      : []),
  ];

  const table = useReactTable({
    data: rows,
    columns,
    getRowId: (_row, index) => String(index),
    getCoreRowModel: getCoreRowModel(),
  });

  return (
    <div className="flex flex-col gap-4">
      <DataGrid table={table} recordCount={rows.length} emptyMessage="No deliverable fields mapped yet.">
        <DataGridTable />
      </DataGrid>

      {editing && (
        <div>
          <Button
            type="button"
            variant="outline"
            size="sm"
            onClick={onAddRow}
            disabled={sorentoFields.length === 0 || allTargetsUsed}
          >
            <Plus className="size-4" />
            Add field
          </Button>
        </div>
      )}

      {provenanceRows.length > 0 && (
        <div className="flex flex-col gap-2 border-t pt-4">
          <span className="text-xs font-medium text-muted-foreground">
            Not delivered to Sorento
          </span>
          <div className="flex flex-col gap-1.5">
            {provenanceRows.map((row) => (
              <div
                key={row.canonicalField}
                className="flex flex-wrap items-center gap-2 text-sm"
              >
                <code className="text-xs">{row.sourcePath}</code>
                <span className="text-muted-foreground">→</span>
                <span className="text-muted-foreground">
                  {humanizeFieldKey(row.canonicalField)}
                </span>
                <Badge variant="secondary" appearance="light" size="sm">
                  Provenance
                </Badge>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
