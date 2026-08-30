'use client';

import { useCallback, useEffect, useMemo, useState } from 'react';
import type {
  AutocountMappingRow,
  AutocountMappingView,
  AutocountMappingWriteRow,
  AutocountSorentoField,
} from '@/types/autocount';
import {
  unmappedRequiredFields,
  type MappingEditableRow,
} from './mapping-table';

/** Deliverable rows (a mappable Sorento target) vs provenance rows (no target). */
export function splitMappingRows(rows: AutocountMappingRow[]): {
  deliverable: MappingEditableRow[];
  provenance: AutocountMappingRow[];
} {
  const deliverable: MappingEditableRow[] = [];
  const provenance: AutocountMappingRow[] = [];
  for (const row of rows) {
    if (row.sorentoField) {
      deliverable.push({
        sourcePath: row.sourcePath,
        transform: row.transform,
        formula: row.formula ?? null,
        sorentoField: row.sorentoField,
      });
    } else {
      provenance.push(row);
    }
  }
  return { deliverable, provenance };
}

export interface UseMappingDraftResult {
  rows: MappingEditableRow[];
  provenance: AutocountMappingRow[];
  sorentoFields: AutocountSorentoField[];
  acFields: string[];
  /** Working rows differ from the loaded view. */
  dirty: boolean;
  /** Required Sorento fields no row maps (AC-15-44) - warned, never silent. */
  unmappedRequired: string[];
  onChangeRow: (index: number, patch: Partial<MappingEditableRow>) => void;
  onAddRow: () => void;
  onRemoveRow: (index: number) => void;
  /** Which row's formula builder is open (null = closed). */
  builderIndex: number | null;
  setBuilderIndex: (index: number | null) => void;
  onApplyFormula: (formula: string) => void;
  simulatorOpen: boolean;
  setSimulatorOpen: (open: boolean) => void;
  /** The rows as the PUT sends them (trimmed source paths). */
  writeRows: () => AutocountMappingWriteRow[];
  /** The foolproof pre-save check - the message to show, or null when sendable. */
  validate: () => string | null;
  /** Revert to the loaded view. */
  reset: () => void;
}

/**
 * The mapping editor's WORKING state (rows, dirty, add/remove/change, builder +
 * simulator toggles) - extracted from the standalone mapping page so the DB
 * task editor's Mapping tab (plan 22 S2, AC-22-09) runs the SAME editor under
 * its own form's Edit/Save, never a parallel one.
 */
export function useMappingDraft(view: AutocountMappingView | null): UseMappingDraftResult {
  const [rows, setRows] = useState<MappingEditableRow[]>([]);
  const [builderIndex, setBuilderIndex] = useState<number | null>(null);
  const [simulatorOpen, setSimulatorOpen] = useState(false);

  // Seed the working rows from the loaded/saved view. Keyed on the deliverable
  // signature so a background reload with identical rows never wipes an edit.
  const baseline = useMemo(() => (view ? splitMappingRows(view.rows).deliverable : []), [view]);
  const baselineKey = useMemo(() => JSON.stringify(baseline), [baseline]);
  useEffect(() => {
    setRows(baseline);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [baselineKey]);

  const provenance = useMemo(() => (view ? splitMappingRows(view.rows).provenance : []), [view]);
  const sorentoFields = useMemo(() => view?.sorentoFields ?? [], [view]);
  const acFields = useMemo(() => view?.acFields ?? [], [view]);

  const dirty = useMemo(() => JSON.stringify(rows) !== baselineKey, [rows, baselineKey]);

  const unmappedRequired = useMemo(
    () => unmappedRequiredFields(rows, sorentoFields),
    [rows, sorentoFields],
  );

  const onChangeRow = useCallback((index: number, patch: Partial<MappingEditableRow>) => {
    setRows((prev) => prev.map((r, i) => (i === index ? { ...r, ...patch } : r)));
  }, []);

  const onAddRow = useCallback(() => {
    setRows((prev) => {
      const used = new Set(prev.map((r) => r.sorentoField));
      const nextTarget = sorentoFields.find((f) => !used.has(f.field));
      return [
        ...prev,
        { sourcePath: '', transform: 'string', formula: null, sorentoField: nextTarget?.field ?? '' },
      ];
    });
  }, [sorentoFields]);

  const onRemoveRow = useCallback((index: number) => {
    setRows((prev) => prev.filter((_, i) => i !== index));
  }, []);

  const onApplyFormula = useCallback(
    (formula: string) => {
      if (builderIndex === null) return;
      // Empty ⇒ the row falls back to its named transform (formula NULL).
      onChangeRow(builderIndex, { formula: formula.trim() ? formula.trim() : null });
    },
    [builderIndex, onChangeRow],
  );

  const writeRows = useCallback(
    (): AutocountMappingWriteRow[] =>
      rows.map((r) => ({
        sourcePath: r.sourcePath.trim(),
        transform: r.transform,
        formula: r.formula,
        sorentoField: r.sorentoField,
      })),
    [rows],
  );

  const validate = useCallback((): string | null => {
    // Foolproof: every row needs a source + a target before it can be sent.
    if (rows.some((r) => !r.sourcePath.trim() || !r.sorentoField)) {
      return 'Every mapping row needs a source and a Sorento field.';
    }
    return null;
  }, [rows]);

  const reset = useCallback(() => setRows(baseline), [baseline]);

  return {
    rows,
    provenance,
    sorentoFields,
    acFields,
    dirty,
    unmappedRequired,
    onChangeRow,
    onAddRow,
    onRemoveRow,
    builderIndex,
    setBuilderIndex,
    onApplyFormula,
    simulatorOpen,
    setSimulatorOpen,
    writeRows,
    validate,
    reset,
  };
}
