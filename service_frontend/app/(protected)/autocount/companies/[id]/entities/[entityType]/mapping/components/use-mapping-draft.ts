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

/** Deliverable rows (a mappable Sorento target) vs provenance rows (no target),
 * for ONE scope (`'header'` or `'line'`, sprint-5/02, AC-02-01). */
export function splitMappingRows(
  rows: AutocountMappingRow[],
  scope: string,
): {
  deliverable: MappingEditableRow[];
  provenance: AutocountMappingRow[];
} {
  const deliverable: MappingEditableRow[] = [];
  const provenance: AutocountMappingRow[] = [];
  for (const row of rows) {
    if (row.scope !== scope) continue;
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

/** One scope's (header or line) working rows + the catalogs it offers. */
export interface MappingDraftScope {
  rows: MappingEditableRow[];
  sorentoFields: AutocountSorentoField[];
  acFields: string[];
  /** Required Sorento fields no row maps (AC-15-44) - warned, never silent. */
  unmappedRequired: string[];
  onChangeRow: (index: number, patch: Partial<MappingEditableRow>) => void;
  onAddRow: () => void;
  onRemoveRow: (index: number) => void;
}

/** Which row's formula builder is open - `null` when closed. */
export interface MappingBuilderTarget {
  scope: 'header' | 'line';
  index: number;
}

export interface UseMappingDraftResult {
  header: MappingDraftScope;
  /**
   * Document entities only (sprint-5/02, AC-02-01/18) - `null` for a
   * master/GRN entity (the view's `lineSorentoFields` came back empty), so
   * the Mapping tab renders a single section unchanged.
   */
  line: MappingDraftScope | null;
  /** Non-deliverable provenance/identity rows (e.g. last_modified), header scope only. */
  provenance: AutocountMappingRow[];
  /** Working rows (either scope) differ from the loaded view. */
  dirty: boolean;
  builderTarget: MappingBuilderTarget | null;
  setBuilderTarget: (target: MappingBuilderTarget | null) => void;
  onApplyFormula: (formula: string) => void;
  simulatorOpen: boolean;
  setSimulatorOpen: (open: boolean) => void;
  /** The rows as the PUT sends them (trimmed source paths, scope-tagged) -
   * BOTH scopes combined, for Simulate previews (which take no wipe/
   * untouched distinction - it never persists anything). */
  writeRows: () => AutocountMappingWriteRow[];
  /**
   * The split a real SAVE needs (security re-review should-fix, sprint-5/02
   * review round): `rows` is header-only; `lineRows` is `undefined` for a
   * master/GRN entity (no Lines tab at all - line scope stays untouched by
   * definition), else the CURRENT line draft (possibly `[]` when the
   * operator cleared it) - the editor's one Save button always resubmits
   * its whole current draft, so a document entity's line scope is always
   * "submitted" on save, an empty array included.
   */
  writeRowsForSave: () => { rows: AutocountMappingWriteRow[]; lineRows?: AutocountMappingWriteRow[] };
  /** The foolproof pre-save check - the message to show, or null when sendable. */
  validate: () => string | null;
  /** Revert to the loaded view. */
  reset: () => void;
}

function useScope(
  view: AutocountMappingView | null,
  scope: 'header' | 'line',
  sorentoFields: AutocountSorentoField[],
  acFields: string[],
): {
  scope: MappingDraftScope;
  provenance: AutocountMappingRow[];
  dirty: boolean;
  baseline: MappingEditableRow[];
  setRows: (rows: MappingEditableRow[] | ((prev: MappingEditableRow[]) => MappingEditableRow[])) => void;
  rows: MappingEditableRow[];
} {
  const [rows, setRows] = useState<MappingEditableRow[]>([]);

  const baseline = useMemo(
    () => (view ? splitMappingRows(view.rows, scope).deliverable : []),
    [view, scope],
  );
  const baselineKey = useMemo(() => JSON.stringify(baseline), [baseline]);
  useEffect(() => {
    setRows(baseline);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [baselineKey]);

  const provenance = useMemo(
    () => (view ? splitMappingRows(view.rows, scope).provenance : []),
    [view, scope],
  );

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

  return {
    scope: { rows, sorentoFields, acFields, unmappedRequired, onChangeRow, onAddRow, onRemoveRow },
    provenance,
    dirty,
    baseline,
    setRows,
    rows,
  };
}

/**
 * The mapping editor's WORKING state - HEADER scope always, plus a LINE
 * scope for document entities (sprint-5/02, AC-02-01/18/21) - extracted from
 * the standalone mapping page so the DB task editor's Mapping tab (plan 22
 * S2, AC-22-09) runs the SAME editor under its own form's Edit/Save, never a
 * parallel one. `line` is `null` whenever the view carries no line targets
 * (a master/GRN entity), so callers render a single section unchanged.
 */
export function useMappingDraft(view: AutocountMappingView | null): UseMappingDraftResult {
  const headerSorentoFields = useMemo(() => view?.sorentoFields ?? [], [view]);
  const headerAcFields = useMemo(() => view?.acFields ?? [], [view]);
  const lineSorentoFields = useMemo(() => view?.lineSorentoFields ?? [], [view]);
  const lineAcFields = useMemo(() => view?.lineAcFields ?? [], [view]);
  const hasLineScope = lineSorentoFields.length > 0;

  const header = useScope(view, 'header', headerSorentoFields, headerAcFields);
  const lineScope = useScope(view, 'line', lineSorentoFields, lineAcFields);

  const [builderTarget, setBuilderTarget] = useState<MappingBuilderTarget | null>(null);
  const [simulatorOpen, setSimulatorOpen] = useState(false);

  const dirty = header.dirty || (hasLineScope && lineScope.dirty);

  const onApplyFormula = useCallback(
    (formula: string) => {
      if (!builderTarget) return;
      const next = formula.trim() ? formula.trim() : null;
      const target = builderTarget.scope === 'header' ? header : lineScope;
      target.scope.onChangeRow(builderTarget.index, { formula: next });
    },
    [builderTarget, header, lineScope],
  );

  const toWrite = useCallback(
    (rows: MappingEditableRow[], scope: 'header' | 'line'): AutocountMappingWriteRow[] =>
      rows.map((r) => ({
        sourcePath: r.sourcePath.trim(),
        transform: r.transform,
        formula: r.formula,
        sorentoField: r.sorentoField,
        scope,
      })),
    [],
  );

  const writeRows = useCallback((): AutocountMappingWriteRow[] => [
    ...toWrite(header.rows, 'header'),
    ...(hasLineScope ? toWrite(lineScope.rows, 'line') : []),
  ], [hasLineScope, header.rows, lineScope.rows, toWrite]);

  const writeRowsForSave = useCallback((): {
    rows: AutocountMappingWriteRow[];
    lineRows?: AutocountMappingWriteRow[];
  } => ({
    rows: toWrite(header.rows, 'header'),
    // `undefined` (no Lines tab at all - master/GRN) vs the current line
    // draft, `[]` included, when this entity HAS one - the wire signal a
    // header-only save needs (security re-review should-fix).
    lineRows: hasLineScope ? toWrite(lineScope.rows, 'line') : undefined,
  }), [hasLineScope, header.rows, lineScope.rows, toWrite]);

  const validate = useCallback((): string | null => {
    // Foolproof: every row needs a source + a target before it can be sent.
    const rowsToCheck = hasLineScope ? [...header.rows, ...lineScope.rows] : header.rows;
    if (rowsToCheck.some((r) => !r.sourcePath.trim() || !r.sorentoField)) {
      return 'Every mapping row needs a source and a Sorento field.';
    }
    return null;
  }, [hasLineScope, header.rows, lineScope.rows]);

  const reset = useCallback(() => {
    header.setRows(header.baseline);
    lineScope.setRows(lineScope.baseline);
  }, [header, lineScope]);

  return {
    header: header.scope,
    line: hasLineScope ? lineScope.scope : null,
    provenance: header.provenance,
    dirty,
    builderTarget,
    setBuilderTarget,
    onApplyFormula,
    simulatorOpen,
    setSimulatorOpen,
    writeRows,
    writeRowsForSave,
    validate,
    reset,
  };
}
