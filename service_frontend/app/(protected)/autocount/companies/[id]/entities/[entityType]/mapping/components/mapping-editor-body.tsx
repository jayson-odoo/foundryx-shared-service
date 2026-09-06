'use client';

import { FlaskConical, TriangleAlert } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Alert, AlertDescription, AlertIcon, AlertTitle } from '@/components/ui/alert';
import {
  AutocountFormulaBuilder,
  type FormulaVariableGroup,
} from '@/components/platform/autocount/formula-builder';
import { MappingSimulator } from '@/components/platform/autocount/mapping-simulator';
import { LINE_AGGREGATES, STATUS_VOCABULARY } from '@/lib/autocount-etl';
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
  /** Overrides the header section's `acFields` as the source picker's option set. */
  sourceOptions?: string[];
  /** Document entities only (sprint-5/02) - overrides the line section's
   *  `acFields` (the task's `line_result_columns` + this session's picks). */
  lineSourceOptions?: string[];
  onServerTest: (formula: string, value: unknown) => Promise<AutocountFormulaTestResult>;
  onSimulate: (
    record: Record<string, unknown>,
    rows: AutocountMappingWriteRow[],
    lines?: Array<Record<string, unknown>>,
  ) => Promise<AutocountSimulateResult>;
  entityLabel: string;
  /** The task's canonical entity key + the current preview's column types -
   * drives the `status` seed-formula pre-fill (S5 review SHOULD-FIX 4c).
   * Both optional so the API-path editor (no typed columns) is unaffected. */
  entityType?: string;
  columnTypes?: Record<string, string>;
  /** Document entities only (sprint-5/02) - the line query's preview column types. */
  lineColumnTypes?: Record<string, string>;
  /**
   * Document entities only (sprint-5/02, AC-02-22) - the Simulate dialog's
   * document mode wiring. Undefined = the master-entity free-JSON simulator
   * (unchanged).
   */
  headerPreviewRows?: Array<Record<string, unknown>>;
  headerKeyColumns?: string[];
  onFetchLines?: (docKey: string) => Promise<Array<Record<string, unknown>>>;
}

/**
 * The mapping editor's surface (AC-15-40..44, slice 16 formulas + simulator)
 * WITHOUT its page chrome: the warnings, the table(s), the formula builder and
 * the simulator. Mounted by the standalone mapping page AND the DB task
 * editor's Mapping tab, each under its own Resource form Edit/Save.
 *
 * Document entities (sprint-5/02, AC-02-18) render TWO sections - "Header
 * fields" and "Line fields" - each the same `MappingTable`; a master/GRN
 * entity (`draft.line === null`) renders the single section unchanged.
 */
export function MappingEditorBody({
  editing,
  draft,
  saveError,
  sourceMode = 'path',
  sourceOptions,
  lineSourceOptions,
  onServerTest,
  onSimulate,
  entityLabel,
  entityType = '',
  columnTypes = {},
  lineColumnTypes = {},
  headerPreviewRows,
  headerKeyColumns,
  onFetchLines,
}: MappingEditorBodyProps) {
  const isDocument = draft.line !== null;
  const target = draft.builderTarget;
  const builderRow = target
    ? (target.scope === 'header' ? draft.header : draft.line)?.rows[target.index] ?? null
    : null;
  const builderPreset = builderRow ? presetForRow(builderRow.transform, builderRow.formula) : 'custom';

  // The formula builder's Variables panel (sprint-5/02, AC-02-20): a
  // document row's header/line columns, `lines.*` aggregates (header rows
  // only), and the status vocabulary as literal chips when the row's target
  // IS `status`. Empty for a master/GRN entity - the builder falls back to
  // its single-`value` model, unchanged.
  const builderVariables: FormulaVariableGroup[] = (() => {
    if (!isDocument || !target || !builderRow) return [];
    const groups: FormulaVariableGroup[] = [];
    const columns = target.scope === 'header' ? (sourceOptions ?? draft.header.acFields) : (lineSourceOptions ?? draft.line?.acFields ?? []);
    if (columns.length > 0) {
      groups.push({
        label: target.scope === 'header' ? 'Header columns' : 'Line columns',
        items: columns.map((c) => ({ label: c, token: c })),
      });
    }
    if (target.scope === 'header') {
      groups.push({
        label: 'Line aggregates',
        items: LINE_AGGREGATES.map((a) => ({ label: a.label, token: a.token })),
      });
    }
    return groups;
  })();
  const builderLiterals =
    isDocument && builderRow?.sorentoField === 'status'
      ? STATUS_VOCABULARY.map((v) => ({ label: v, token: `"${v}"` }))
      : undefined;

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

      {draft.header.unmappedRequired.length > 0 && (
        <Alert variant="warning" appearance="light" data-testid="unmapped-required-warning">
          <AlertIcon>
            <TriangleAlert />
          </AlertIcon>
          <AlertTitle>
            {draft.header.unmappedRequired.map(sorentoFieldLabel).join(', ')} not mapped
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

      <div className="flex flex-col gap-2">
        {isDocument && (
          <h3 className="text-sm font-medium text-foreground">Header fields</h3>
        )}
        <MappingTable
          editing={editing}
          rows={draft.header.rows}
          provenanceRows={draft.provenance}
          sorentoFields={draft.header.sorentoFields}
          acFields={sourceOptions ?? draft.header.acFields}
          sourceMode={sourceMode}
          onChangeRow={draft.header.onChangeRow}
          onAddRow={draft.header.onAddRow}
          onRemoveRow={draft.header.onRemoveRow}
          onBuildRow={(index) => draft.setBuilderTarget({ scope: 'header', index })}
          entityType={entityType}
          columnTypes={columnTypes}
        />
      </div>

      {draft.line && (
        <div className="flex flex-col gap-2 border-t pt-4">
          <h3 className="text-sm font-medium text-foreground">Line fields</h3>
          {draft.line.unmappedRequired.length > 0 && (
            <Alert variant="warning" appearance="light" data-testid="unmapped-required-line-warning">
              <AlertIcon>
                <TriangleAlert />
              </AlertIcon>
              <AlertTitle>
                {draft.line.unmappedRequired.map(sorentoFieldLabel).join(', ')} not mapped
              </AlertTitle>
              <AlertDescription>
                A required Sorento line field with no source will fail the sync.
              </AlertDescription>
            </Alert>
          )}
          <MappingTable
            editing={editing}
            rows={draft.line.rows}
            provenanceRows={[]}
            sorentoFields={draft.line.sorentoFields}
            acFields={lineSourceOptions ?? draft.line.acFields}
            sourceMode={sourceMode}
            onChangeRow={draft.line.onChangeRow}
            onAddRow={draft.line.onAddRow}
            onRemoveRow={draft.line.onRemoveRow}
            onBuildRow={(index) => draft.setBuilderTarget({ scope: 'line', index })}
            entityType={entityType}
            columnTypes={lineColumnTypes}
          />
        </div>
      )}

      {builderRow && (
        <AutocountFormulaBuilder
          open={target !== null}
          onOpenChange={(open) => {
            if (!open) draft.setBuilderTarget(null);
          }}
          // Pre-fill from the row's formula, else the preset's canonical formula
          // so a Date/Boolean row opens showing its expression to edit (AC-16-10).
          value={builderRow.formula ?? presetFormula(builderPreset)}
          onApply={draft.onApplyFormula}
          onServerTest={onServerTest}
          fieldLabel={sorentoFieldLabel(builderRow.sorentoField)}
          initialCategory={builderPreset === 'date' ? 'Date' : 'All'}
          variables={builderVariables.length > 0 ? builderVariables : undefined}
          literalOptions={builderLiterals}
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
        headerPreviewRows={isDocument ? headerPreviewRows : undefined}
        headerKeyColumns={headerKeyColumns}
        onFetchLines={isDocument ? onFetchLines : undefined}
      />
    </div>
  );
}
