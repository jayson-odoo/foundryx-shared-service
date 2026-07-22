'use client';

import { useCallback, useEffect, useMemo, useState } from 'react';
import Link from 'next/link';
import { FlaskConical, Info, LoaderCircleIcon, TriangleAlert } from 'lucide-react';
import { useForm } from 'react-hook-form';
import { toast } from 'sonner';
import { Container } from '@/components/common/container';
import { Button } from '@/components/ui/button';
import { Form } from '@/components/ui/form';
import {
  Alert,
  AlertDescription,
  AlertIcon,
  AlertTitle,
} from '@/components/ui/alert';
import { ResourceForm, type ResourceFormConfig } from '@/components/platform/resource-form';
import { AutocountFormulaBuilder } from '@/components/platform/autocount/formula-builder';
import { MappingSimulator } from '@/components/platform/autocount/mapping-simulator';
import { useCan } from '@/hooks/use-can';
import { useAutocountCompany } from '@/hooks/use-autocount-company';
import { useAutocountMapping } from '@/hooks/use-autocount-mapping';
import type { AutocountMappingRow } from '@/types/autocount';
import {
  AC_COMPANIES_MANAGE,
  AC_COMPANIES_PATH,
  acCompanyHref,
  entityLabel,
  presetFormula,
  presetForRow,
} from '../../../../../../components/autocount-meta';
import {
  MappingTable,
  sorentoFieldLabel,
  unmappedRequiredFields,
  type MappingEditableRow,
} from './mapping-table';

/** Deliverable rows (a mappable Sorento target) vs provenance rows (no target). */
function splitRows(rows: AutocountMappingRow[]): {
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

export interface MappingEditorViewProps {
  companyId: string;
  entityType: string;
}

/**
 * The per-(company, entity) field-mapping editor (AC-15-40..44) on the Resource
 * form shell: read-only by default, editable under the global Edit toggle, saved
 * through the form's single dirty-guarded save. Presents AutoCount source →
 * Sorento field directly (G1); the Sorento picker offers only accepted targets.
 */
export function MappingEditorView({ companyId, entityType }: MappingEditorViewProps) {
  const { can } = useCan();
  const form = useForm();
  const { detail } = useAutocountCompany(companyId);
  const { view, isLoading, notFound, saveError, save, testFormula, simulate } =
    useAutocountMapping(companyId, entityType);

  const [rows, setRows] = useState<MappingEditableRow[]>([]);
  // Which row's formula builder is open (null = closed), and the simulator.
  const [builderIndex, setBuilderIndex] = useState<number | null>(null);
  const [simulatorOpen, setSimulatorOpen] = useState(false);

  // Seed the working rows from the loaded/saved view. Keyed on the deliverable
  // signature so a background reload with identical rows never wipes an edit.
  const baseline = useMemo(
    () => (view ? splitRows(view.rows).deliverable : []),
    [view],
  );
  const baselineKey = useMemo(() => JSON.stringify(baseline), [baseline]);
  useEffect(() => {
    setRows(baseline);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [baselineKey]);

  const provenance = useMemo(
    () => (view ? splitRows(view.rows).provenance : []),
    [view],
  );

  const sorentoFields = useMemo(() => view?.sorentoFields ?? [], [view]);
  const acFields = useMemo(() => view?.acFields ?? [], [view]);

  const dirty = useMemo(
    () => JSON.stringify(rows) !== baselineKey,
    [rows, baselineKey],
  );

  const unmappedRequired = useMemo(
    () => unmappedRequiredFields(rows, sorentoFields),
    [rows, sorentoFields],
  );

  const onChangeRow = useCallback(
    (index: number, patch: Partial<MappingEditableRow>) => {
      setRows((prev) => prev.map((r, i) => (i === index ? { ...r, ...patch } : r)));
    },
    [],
  );

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

  const onBuildRow = useCallback((index: number) => setBuilderIndex(index), []);

  const onApplyFormula = useCallback(
    (formula: string) => {
      if (builderIndex === null) return;
      // Empty ⇒ the row falls back to its named transform (formula NULL).
      onChangeRow(builderIndex, { formula: formula.trim() ? formula.trim() : null });
    },
    [builderIndex, onChangeRow],
  );

  const onSave = useCallback(async (): Promise<boolean> => {
    // Foolproof: every row needs a source + a target before it can be sent.
    if (rows.some((r) => !r.sourcePath.trim() || !r.sorentoField)) {
      toast.error('Every mapping row needs an AutoCount source and a Sorento field.');
      return false;
    }
    const ok = await save(
      rows.map((r) => ({
        sourcePath: r.sourcePath.trim(),
        transform: r.transform,
        formula: r.formula,
        sorentoField: r.sorentoField,
      })),
    );
    if (ok) toast.success('Field mapping saved.');
    return ok;
  }, [rows, save]);

  const onCancel = useCallback(() => setRows(baseline), [baseline]);

  const config = useMemo<ResourceFormConfig<AutocountMappingRow> | null>(() => {
    if (!view) return null;
    const companyName = detail?.company.name;
    return {
      breadcrumb: [
        { label: 'AutoCount' },
        { label: 'Companies', href: AC_COMPANIES_PATH },
        ...(companyName
          ? [{ label: companyName, href: acCompanyHref(companyId) }]
          : []),
        { label: `${entityLabel(entityType)} mapping` },
      ],
      backHref: acCompanyHref(companyId),
      title: `${entityLabel(entityType)} field mapping`,
      subtitle: companyName ?? undefined,
      tabs: [
        {
          id: 'mapping',
          label: 'Mapping',
          icon: Info,
          render: ({ editing }) => (
            <div className="flex flex-col gap-4 py-2">
              <div className="flex justify-end">
                <Button
                  type="button"
                  variant="outline"
                  size="sm"
                  onClick={() => setSimulatorOpen(true)}
                >
                  <FlaskConical className="size-4" />
                  Simulate mapping
                </Button>
              </div>
              {unmappedRequired.length > 0 && (
                <Alert
                  variant="warning"
                  appearance="light"
                  data-testid="unmapped-required-warning"
                >
                  <AlertIcon>
                    <TriangleAlert />
                  </AlertIcon>
                  <AlertTitle>
                    {unmappedRequired.map(sorentoFieldLabel).join(', ')} not mapped
                  </AlertTitle>
                  <AlertDescription>
                    A required Sorento field with no source will fail the sync.
                  </AlertDescription>
                </Alert>
              )}
              {saveError && (
                <Alert
                  variant="destructive"
                  appearance="light"
                  data-testid="mapping-save-error"
                >
                  <AlertIcon>
                    <TriangleAlert />
                  </AlertIcon>
                  <AlertTitle>{saveError}</AlertTitle>
                </Alert>
              )}
              <MappingTable
                editing={editing && can(AC_COMPANIES_MANAGE)}
                rows={rows}
                provenanceRows={provenance}
                sorentoFields={sorentoFields}
                acFields={acFields}
                onChangeRow={onChangeRow}
                onAddRow={onAddRow}
                onRemoveRow={onRemoveRow}
                onBuildRow={onBuildRow}
              />
            </div>
          ),
        },
      ],
      initialTabId: 'mapping',
      actions: [],
      actionRows: [],
      editable: true,
      editPermission: AC_COMPANIES_MANAGE,
      isDirty: dirty,
      onSave,
      onCancel,
    };
  }, [
    acFields,
    can,
    companyId,
    detail,
    dirty,
    entityType,
    onAddRow,
    onBuildRow,
    onCancel,
    onChangeRow,
    onRemoveRow,
    onSave,
    provenance,
    rows,
    saveError,
    sorentoFields,
    unmappedRequired,
    view,
  ]);

  if (isLoading && !view) {
    return (
      <Container width="fluid">
        <div className="flex items-center justify-center py-24 text-muted-foreground">
          <LoaderCircleIcon className="size-6 animate-spin" />
        </div>
      </Container>
    );
  }

  if (notFound || !config) {
    return (
      <Container width="fluid">
        <div className="flex flex-col items-center gap-3 py-24 text-center">
          <p className="text-sm font-medium">Mapping not found.</p>
          <Button variant="outline" size="sm" asChild>
            <Link href={acCompanyHref(companyId)}>Back to company</Link>
          </Button>
        </div>
      </Container>
    );
  }

  const builderRow = builderIndex !== null ? rows[builderIndex] : null;
  const builderPreset = builderRow
    ? presetForRow(builderRow.transform, builderRow.formula)
    : 'custom';

  return (
    <Container width="fluid">
      <Form {...form}>
        <ResourceForm config={config} />
      </Form>

      {builderRow && (
        <AutocountFormulaBuilder
          open={builderIndex !== null}
          onOpenChange={(open) => {
            if (!open) setBuilderIndex(null);
          }}
          // Pre-fill from the row's formula, else the preset's canonical formula
          // so a Date/Boolean row opens showing its expression to edit (AC-16-10).
          value={builderRow.formula ?? presetFormula(builderPreset)}
          onApply={onApplyFormula}
          onServerTest={testFormula}
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
        open={simulatorOpen}
        onOpenChange={setSimulatorOpen}
        rows={rows.map((r) => ({
          sourcePath: r.sourcePath.trim(),
          transform: r.transform,
          formula: r.formula,
          sorentoField: r.sorentoField,
        }))}
        onSimulate={(record, draftRows) => simulate(record, draftRows)}
        entityLabel={entityLabel(entityType)}
      />
    </Container>
  );
}
