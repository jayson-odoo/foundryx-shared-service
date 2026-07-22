'use client';

import { ArrowRight, FunctionSquare, Plus, Trash2 } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import { SearchSelect } from '@/components/platform/search-select';
import { ClampedText } from '@/components/platform/clamped-text';
import { humanizeFieldKey } from '@/lib/autocount-diff';
import type {
  AutocountMappingRow,
  AutocountSorentoField,
} from '@/types/autocount';
import {
  AC_PRESET_OPTIONS,
  applyPreset,
  presetForRow,
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
 * mapping them — the exact null-record failure a sync would hit. Warned before
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

export interface MappingTableProps {
  editing: boolean;
  rows: MappingEditableRow[];
  /** Non-deliverable provenance/identity rows (e.g. last_modified) — read-only. */
  provenanceRows: AutocountMappingRow[];
  /** The ONLY Sorento targets the picker offers (AC-15-42). */
  sorentoFields: AutocountSorentoField[];
  /** Known AutoCount source paths; a free dotted path is still allowed. */
  acFields: string[];
  onChangeRow: (index: number, patch: Partial<MappingEditableRow>) => void;
  onAddRow: () => void;
  onRemoveRow: (index: number) => void;
  /** Open the formula builder for a row (AC-16-11). */
  onBuildRow: (index: number) => void;
}

/**
 * The AutoCount source → (transform) → Sorento field table (AC-15-40). Read-only
 * by default (plain values); under Edit each cell is a searchable picker. The
 * Sorento picker offers ONLY the accepted set (and never a target already used
 * by another row — a duplicate can't even be selected), so the foolproof-UI
 * guard is enforced in the UI as well as server-side.
 */
export function MappingTable({
  editing,
  rows,
  provenanceRows,
  sorentoFields,
  acFields,
  onChangeRow,
  onAddRow,
  onRemoveRow,
  onBuildRow,
}: MappingTableProps) {
  const sourceOptions = acFields.map((f) => ({ label: f, value: f }));
  const usedTargets = new Set(rows.map((r) => r.sorentoField).filter(Boolean));
  const allTargetsUsed = sorentoFields.every((f) => usedTargets.has(f.field));

  return (
    <div className="flex flex-col gap-4">
      <div className="overflow-x-auto">
        <table className="w-full min-w-[640px] text-sm">
          <thead>
            <tr className="border-b text-start text-xs font-medium text-muted-foreground">
              <th className="px-2 py-2 text-start font-medium">AutoCount field</th>
              <th className="px-2 py-2 text-start font-medium">Transform</th>
              <th className="w-6 px-2 py-2" aria-hidden />
              <th className="px-2 py-2 text-start font-medium">Sorento field</th>
              {editing && <th className="w-10 px-2 py-2" aria-hidden />}
            </tr>
          </thead>
          <tbody>
            {rows.length === 0 && (
              <tr>
                <td
                  colSpan={editing ? 5 : 4}
                  className="px-2 py-6 text-center text-muted-foreground"
                >
                  No deliverable fields mapped yet.
                </td>
              </tr>
            )}
            {rows.map((row, index) => {
              // Foolproof: offer this row's own target + any not used elsewhere,
              // so a duplicate target can never be selected.
              const targetOptions = sorentoFields
                .filter((f) => f.field === row.sorentoField || !usedTargets.has(f.field))
                .map((f) => ({
                  label: f.required ? `${sorentoFieldLabel(f.field)} *` : sorentoFieldLabel(f.field),
                  value: f.field,
                }));
              return (
                <tr key={index} className="border-b align-top">
                  <td className="px-2 py-2">
                    {editing ? (
                      <SearchSelect
                        options={sourceOptions}
                        value={row.sourcePath}
                        onChange={(value) => onChangeRow(index, { sourcePath: value })}
                        placeholder="Select or type a path"
                        searchPlaceholder="Search or type a dotted path"
                        allowCustom
                        ariaLabel={`AutoCount source for row ${index + 1}`}
                      />
                    ) : (
                      <code className="text-xs">{row.sourcePath}</code>
                    )}
                  </td>
                  <td className="px-2 py-2">
                    {editing ? (
                      <div className="flex items-center gap-1">
                        <div className="min-w-28 flex-1">
                          <SearchSelect
                            options={AC_PRESET_OPTIONS}
                            value={presetForRow(row.transform, row.formula)}
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
                        <span className="text-muted-foreground">{presetLabel(row)}</span>
                        {row.formula && (
                          <ClampedText
                            text={row.formula}
                            lines={2}
                            className="font-mono text-[11px] text-muted-foreground/80"
                          />
                        )}
                      </div>
                    )}
                  </td>
                  <td className="px-2 py-3 text-muted-foreground">
                    <ArrowRight className="size-4" />
                  </td>
                  <td className="px-2 py-2">
                    {editing ? (
                      <SearchSelect
                        options={targetOptions}
                        value={row.sorentoField}
                        onChange={(value) => onChangeRow(index, { sorentoField: value })}
                        placeholder="Select a Sorento field"
                        disabled={sorentoFields.length === 0}
                        ariaLabel={`Sorento field for row ${index + 1}`}
                      />
                    ) : (
                      <span className="font-medium text-foreground">
                        {sorentoFieldLabel(row.sorentoField)}
                      </span>
                    )}
                  </td>
                  {editing && (
                    <td className="px-2 py-2 text-end">
                      <Button
                        type="button"
                        variant="ghost"
                        size="sm"
                        mode="icon"
                        onClick={() => onRemoveRow(index)}
                        aria-label={`Remove row ${index + 1}`}
                      >
                        <Trash2 className="size-4" />
                      </Button>
                    </td>
                  )}
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>

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
