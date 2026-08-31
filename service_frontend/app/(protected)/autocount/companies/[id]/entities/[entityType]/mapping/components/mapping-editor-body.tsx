'use client';

import { FlaskConical, TriangleAlert } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Alert, AlertDescription, AlertIcon, AlertTitle } from '@/components/ui/alert';
import { AutocountFormulaBuilder } from '@/components/platform/autocount/formula-builder';
import { MappingSimulator } from '@/components/platform/autocount/mapping-simulator';
import type {
  AutocountFormulaTestResult,
  AutocountMappingWriteRow,
  AutocountSimulateResult,
} from '@/types/autocount';
import { presetFormula, presetForRow } from '../../../../../../components/autocount-meta';
import { MappingTable, sorentoFieldLabel, type MappingSourceMode } from './mapping-table';
import type { UseMappingDraftResult } from './use-mapping-draft';

export interface MappingEditorBodyProps {
  editing: boolean;
  draft: UseMappingDraftResult;
  /** Last save rejection, surfaced inline (AC-15-44). */
  saveError: string | null;
  /**
   * `path` = the API path's free dotted vendor path (default); `column` = a DB
   * task's preview result columns ONLY (plan 22 S2, AC-22-09).
   */
  sourceMode?: MappingSourceMode;
  /** Overrides the view's `acFields` as the source picker's option set. */
  sourceOptions?: string[];
  onServerTest: (formula: string, value: unknown) => Promise<AutocountFormulaTestResult>;
  onSimulate: (
    record: Record<string, unknown>,
    rows: AutocountMappingWriteRow[],
  ) => Promise<AutocountSimulateResult>;
  entityLabel: string;
  /** The task's canonical entity key + the current preview's column types -
   * drives the `status` seed-formula pre-fill (S5 review SHOULD-FIX 4c).
   * Both optional so the API-path editor (no typed columns) is unaffected. */
  entityType?: string;
  columnTypes?: Record<string, string>;
}

/**
 * The mapping editor's surface (AC-15-40..44, slice 16 formulas + simulator)
 * WITHOUT its page chrome: the warnings, the table, the formula builder and
 * the simulator. Mounted by the standalone mapping page AND the DB task
 * editor's Mapping tab, each under its own Resource form Edit/Save.
 */
export function MappingEditorBody({
  editing,
  draft,
  saveError,
  sourceMode = 'path',
  sourceOptions,
  onServerTest,
  onSimulate,
  entityLabel,
  entityType = '',
  columnTypes = {},
}: MappingEditorBodyProps) {
  const builderRow = draft.builderIndex !== null ? draft.rows[draft.builderIndex] : null;
  const builderPreset = builderRow
    ? presetForRow(builderRow.transform, builderRow.formula)
    : 'custom';

  return (
    <div className="flex flex-col gap-4">
      <div className="flex justify-end">
        <Button
          type="button"
          variant="outline"
          size="sm"
          onClick={() => draft.setSimulatorOpen(true)}
        >
          <FlaskConical className="size-4" />
          Simulate mapping
        </Button>
      </div>
      {draft.unmappedRequired.length > 0 && (
        <Alert variant="warning" appearance="light" data-testid="unmapped-required-warning">
          <AlertIcon>
            <TriangleAlert />
          </AlertIcon>
          <AlertTitle>
            {draft.unmappedRequired.map(sorentoFieldLabel).join(', ')} not mapped
          </AlertTitle>
          <AlertDescription>
            A required Sorento field with no source will fail the sync.
          </AlertDescription>
        </Alert>
      )}
      {saveError && (
        <Alert variant="destructive" appearance="light" data-testid="mapping-save-error">
          <AlertIcon>
            <TriangleAlert />
          </AlertIcon>
          <AlertTitle>{saveError}</AlertTitle>
        </Alert>
      )}
      <MappingTable
        editing={editing}
        rows={draft.rows}
        provenanceRows={draft.provenance}
        sorentoFields={draft.sorentoFields}
        acFields={sourceOptions ?? draft.acFields}
        sourceMode={sourceMode}
        onChangeRow={draft.onChangeRow}
        onAddRow={draft.onAddRow}
        onRemoveRow={draft.onRemoveRow}
        onBuildRow={draft.setBuilderIndex}
        entityType={entityType}
        columnTypes={columnTypes}
      />

      {builderRow && (
        <AutocountFormulaBuilder
          open={draft.builderIndex !== null}
          onOpenChange={(open) => {
            if (!open) draft.setBuilderIndex(null);
          }}
          // Pre-fill from the row's formula, else the preset's canonical formula
          // so a Date/Boolean row opens showing its expression to edit (AC-16-10).
          value={builderRow.formula ?? presetFormula(builderPreset)}
          onApply={draft.onApplyFormula}
          onServerTest={onServerTest}
          fieldLabel={sorentoFieldLabel(builderRow.sorentoField)}
          initialCategory={builderPreset === 'date' ? 'Date' : 'All'}
          note={
            builderPreset === 'decimal'
              ? 'The Decimal preset keeps exact money precision; a number(value) formula routes through floating point.'
              : undefined
          }
        />
      )}

      <MappingSimulator
        open={draft.simulatorOpen}
        onOpenChange={draft.setSimulatorOpen}
        rows={draft.writeRows()}
        onSimulate={onSimulate}
        entityLabel={entityLabel}
      />
    </div>
  );
}
