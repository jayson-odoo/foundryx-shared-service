'use client';

import { useCallback, useMemo, useState } from 'react';
import Link from 'next/link';
import { Lock, Play, TriangleAlert, Wand2 } from 'lucide-react';
import { Alert, AlertIcon, AlertTitle } from '@/components/ui/alert';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { MultiSelect } from '@/components/platform/multi-select';
import { SearchSelect } from '@/components/platform/search-select';
import { ClampedText } from '@/components/platform/clamped-text';
import { AutocountFormulaBuilder } from '@/components/platform/autocount/formula-builder';
import { SqlEditor } from '@/components/platform/autocount/sql-editor';
import { SqlPreviewGrid } from '@/components/platform/autocount/sql-preview-grid';
import { SqlSchemaTree } from '@/components/platform/autocount/sql-schema-tree';
import type {
  UseAutocountSqlSchemaResult,
  UseSqlPreviewResult,
} from '@/hooks/use-autocount-etl';
import {
  isDocumentEntity,
  pickerColumnOptions,
  previewBadgeText,
  starterQuery,
} from '@/lib/autocount-etl';
import type {
  AutocountEtlSourceConfig,
  AutocountFormulaTestResult,
  AutocountMappingPreset,
  AutocountSqlConnection,
} from '@/types/autocount';

/**
 * The company connection a DB company's task is locked to (AC-01-19): shown
 * as a read-only row where the API company has a picker. The editor seeds it
 * into the config BASELINE (never a post-mount patch, which would dirty an
 * untouched editor), so the save never has to guess.
 */
export interface LockedConnection {
  id: string;
  /** `name · database` when the connection is loaded; the company database until then. */
  label: string;
}

export interface QueryTabProps {
  editing: boolean;
  entityType: string;
  config: AutocountEtlSourceConfig;
  onChange: (patch: Partial<AutocountEtlSourceConfig>) => void;
  connections: AutocountSqlConnection[];
  connectionsLoading: boolean;
  /** Set on a DB company - replaces the Connection picker with a read-only row. */
  lockedConnection?: LockedConnection | null;
  schema: UseAutocountSqlSchemaResult;
  preview: UseSqlPreviewResult;
  /** Documents only (plan 22 S5) - a SEPARATE preview instance for the line
   * query, so testing it never clobbers the header preview's state. */
  linePreview: UseSqlPreviewResult;
  /** Per-field 422 errors from the last save (AC-22-11). */
  fieldErrors: Record<string, string>;
  /**
   * Document entities only (sprint-5/02, AC-02-16/17) - the AutoCount
   * SQL-pack preset for THIS entity, already substituted for the company's
   * database. Empty/undefined = "Use preset" is not offered (foolproof-UI -
   * never show a picker with nothing that would work).
   */
  presets?: AutocountMappingPreset[];
  onUsePreset?: (preset: AutocountMappingPreset) => void;
  /** Server-authoritative single-formula eval, backing the Filter field's
   * `AutocountFormulaBuilder` Testing tab (AC-02-11/20). */
  onServerTest: (formula: string, value: unknown) => Promise<AutocountFormulaTestResult>;
}

const NO_WATERMARK = '';

/** Read-mode rendering of a column pick (chips, never free text). */
function ColumnChips({ values, empty }: { values: string[]; empty: string }) {
  if (values.length === 0) {
    return <span className="text-sm text-muted-foreground">{empty}</span>;
  }
  return (
    <div className="flex flex-wrap gap-1">
      {values.map((v) => (
        <Badge key={v} variant="secondary" appearance="light" className="font-mono">
          {v}
        </Badge>
      ))}
    </div>
  );
}

/**
 * The task editor's Query tab (AC-22-07): schema tree | SQL editor + Test
 * Query + preview grid, then the key/watermark/compared-column pickers fed by
 * the preview's result columns (dropdowns, never free text). Document entities
 * add the per-header line query and the from-date.
 */
export function QueryTab({
  editing,
  entityType,
  config,
  onChange,
  connections,
  connectionsLoading,
  lockedConnection = null,
  schema,
  preview,
  linePreview,
  fieldErrors,
  presets = [],
  onUsePreset,
  onServerTest,
}: QueryTabProps) {
  const isDocument = isDocumentEntity(entityType);
  const connection = connections.find((c) => c.id === config.connectionId) ?? null;
  const [filterBuilderOpen, setFilterBuilderOpen] = useState(false);

  const previewColumns = useMemo(
    () => (preview.state.status === 'success' ? preview.state.preview.columns.map((c) => c.name) : []),
    [preview.state],
  );
  // The Filter builder's Variables panel (AC-02-11/20) - the header columns
  // known so far, plus whatever the saved formula already references (a
  // stale-but-visible variable, same discoverability as `pickerColumnOptions`).
  const filterKnownColumns = useMemo(
    () => pickerColumnOptions(previewColumns, config.keyColumns),
    [config.keyColumns, previewColumns],
  );
  const filterVariables = useMemo(
    () =>
      filterKnownColumns.length > 0
        ? [{ label: 'Header columns', items: filterKnownColumns.map((c) => ({ label: c, token: c })) }]
        : [],
    [filterKnownColumns],
  );
  const docDateOptions = useMemo(
    () => previewColumns.map((c) => ({ label: c, value: c })),
    [previewColumns],
  );

  const savedPicks = useMemo(
    () => [
      ...config.keyColumns,
      ...(config.watermarkColumn ? [config.watermarkColumn] : []),
      ...config.comparedColumns,
    ],
    [config.comparedColumns, config.keyColumns, config.watermarkColumn],
  );
  const columnOptions = useMemo(
    () => pickerColumnOptions(previewColumns, savedPicks).map((c) => ({ label: c, value: c })),
    [previewColumns, savedPicks],
  );
  // Compared columns never include a key column (keys are identity, not change).
  const comparedOptions = useMemo(
    () => columnOptions.filter((o) => !config.keyColumns.includes(o.value)),
    [columnOptions, config.keyColumns],
  );
  // BL-SS-052 (foolproof-UI half) - the watermark column is GUARANTEED to
  // change on every update, so it can never also be a key column (a
  // reconcile would mint a "new" ref for the same real-world record every
  // time). Withhold the chosen watermark from the key-columns picker...
  const keyColumnOptions = useMemo(
    () => columnOptions.filter((o) => o.value !== config.watermarkColumn),
    [columnOptions, config.watermarkColumn],
  );
  const watermarkOptions = useMemo(() => {
    // ...and withhold the chosen key columns from the watermark picker,
    // the same rule from the other picker's side.
    const base = columnOptions.filter((o) => !config.keyColumns.includes(o.value));
    // A document task REQUIRES a watermark column (AutoCount stamps a
    // header's LastModified on any line edit - the S5 line-change-detection
    // decision), so "None" is never a valid choice for one (foolproof-UI -
    // only offer options that can actually work).
    return isDocument ? base : [{ label: 'None', value: NO_WATERMARK }, ...base];
  }, [columnOptions, config.keyColumns, isDocument]);
  const pickersEnabled = editing && columnOptions.length > 0;

  const canTest = Boolean(config.connectionId) && config.query.trim().length > 0 &&
    preview.state.status !== 'loading';
  const canTestLine = Boolean(config.connectionId) && Boolean(config.lineQuery?.trim()) &&
    linePreview.state.status !== 'loading';

  const onTest = useCallback(() => {
    if (!config.connectionId) return;
    void preview.run(config.connectionId, config.query);
  }, [config.connectionId, config.query, preview]);

  const onTestLine = useCallback(() => {
    if (!config.connectionId || !config.lineQuery) return;
    // A harmless NULL bind (never real filtered data at picker-config time)
    // - just enough for the query to execute so its columns populate the
    // line-column pickers below.
    void linePreview.run(config.connectionId, config.lineQuery, { bindDocKey: true, docKey: null });
  }, [config.connectionId, config.lineQuery, linePreview]);

  const onInsertStarter = useCallback(
    (schemaName: string, tableName: string) => {
      onChange({ query: starterQuery(schemaName, tableName) });
    },
    [onChange],
  );

  const onConnectionChange = useCallback(
    (id: string) => {
      onChange({ connectionId: id });
      preview.reset();
      linePreview.reset();
    },
    [onChange, preview, linePreview],
  );

  const onKeyColumnsChange = useCallback(
    (keys: string[]) => {
      onChange({
        keyColumns: keys,
        comparedColumns: config.comparedColumns.filter((c) => !keys.includes(c)),
      });
    },
    [config.comparedColumns, onChange],
  );

  const connectionOptions = connections.map((c) => ({
    label: `${c.name} · ${c.database}`,
    value: c.id,
  }));

  return (
    <div className="flex flex-col gap-4">
      {!lockedConnection && !connectionsLoading && connections.length === 0 && (
        <Alert variant="warning" appearance="light" data-testid="no-sql-connection">
          <AlertIcon>
            <TriangleAlert />
          </AlertIcon>
          <AlertTitle>
            No SQL database connection yet.{' '}
            <Link href="/settings/integrations/new" className="underline">
              Add one in Integrations
            </Link>
          </AlertTitle>
        </Alert>
      )}

      <div className="grid gap-4 lg:grid-cols-[280px_minmax(0,1fr)]">
        {/* Schema tree - scrolls within the editor's height on desktop, stacks
            above the editor on mobile (side panels never stretch the page). */}
        <aside className="rounded-lg border border-border bg-muted/30 p-3 lg:max-h-[calc(100vh-18rem)] lg:overflow-y-auto">
          <SqlSchemaTree
            schema={schema.schema}
            isLoading={schema.isLoading}
            error={schema.error}
            noConnection={!config.connectionId}
            onRefresh={schema.refresh}
            onInsertQuery={onInsertStarter}
            canInsert={editing}
          />
        </aside>

        <div className="flex min-w-0 flex-col gap-4">
          <div className="flex flex-wrap items-end gap-3">
            <div className="flex min-w-0 flex-1 flex-col gap-1.5 sm:max-w-sm">
              <Label htmlFor="etl-connection">Connection</Label>
              {lockedConnection ? (
                <span
                  className="flex min-h-8.5 items-center gap-1.5 text-sm text-foreground"
                  data-testid="locked-connection"
                >
                  <Lock className="size-3.5 shrink-0 text-muted-foreground" aria-hidden />
                  {lockedConnection.label}
                </span>
              ) : (
                <SearchSelect
                  options={connectionOptions}
                  value={config.connectionId}
                  onChange={onConnectionChange}
                  placeholder={connectionsLoading ? 'Loading…' : 'Select a connection'}
                  disabled={!editing || connectionsLoading || connections.length === 0}
                  ariaLabel="Connection"
                />
              )}
            </div>
            {isDocument && presets.length > 0 && (
              <div className="flex min-w-0 flex-col gap-1.5 sm:max-w-xs">
                <Label htmlFor="etl-preset">Use preset</Label>
                <SearchSelect
                  options={presets.map((p) => ({ label: p.label, value: p.entityType }))}
                  value=""
                  onChange={(entityKey) => {
                    const preset = presets.find((p) => p.entityType === entityKey);
                    if (preset) onUsePreset?.(preset);
                  }}
                  placeholder="Choose a preset"
                  disabled={!editing}
                  ariaLabel="Use preset"
                />
              </div>
            )}
            <Button
              type="button"
              variant="primary"
              size="sm"
              onClick={onTest}
              disabled={!canTest}
              data-testid="sql-test-query"
            >
              <Play className="size-3.5" />
              Test query
            </Button>
            {preview.state.status === 'success' && (
              <Badge
                variant={preview.state.preview.rowCount === 0 ? 'secondary' : 'success'}
                appearance="light"
                data-testid="sql-preview-badge"
              >
                {previewBadgeText(preview.state.preview)}
              </Badge>
            )}
          </div>

          <div className="flex flex-col gap-1.5">
            <Label>{isDocument ? 'Header query' : 'Query'}</Label>
            <SqlEditor
              value={config.query}
              onChange={(query) => onChange({ query })}
              editing={editing}
              schema={schema.schema}
              dialect={connection?.dialect ?? schema.schema?.dialect ?? null}
              ariaLabel={isDocument ? 'Header query' : 'Query'}
            />
            {fieldErrors.query && (
              <p className="text-xs text-destructive">{fieldErrors.query}</p>
            )}
          </div>

          {isDocument && (
            <div className="flex flex-col gap-4 rounded-lg border border-border p-4">
              <div className="flex flex-wrap items-end gap-3">
                <div className="flex min-w-0 flex-1 flex-col gap-1.5">
                  <Label>Line query</Label>
                  <SqlEditor
                    value={config.lineQuery ?? ''}
                    onChange={(lineQuery) => onChange({ lineQuery })}
                    editing={editing}
                    schema={schema.schema}
                    dialect={connection?.dialect ?? schema.schema?.dialect ?? null}
                    ariaLabel="Line query"
                    testId="sql-line-editor"
                  />
                  {fieldErrors.lineQuery && (
                    <p className="text-xs text-destructive">{fieldErrors.lineQuery}</p>
                  )}
                </div>
              </div>
              <div className="flex items-center gap-3">
                <Button
                  type="button"
                  variant="primary"
                  size="sm"
                  onClick={onTestLine}
                  disabled={!canTestLine}
                  data-testid="sql-test-line-query"
                >
                  <Play className="size-3.5" />
                  Test line query
                </Button>
                {linePreview.state.status === 'success' && (
                  <Badge
                    variant={linePreview.state.preview.rowCount === 0 ? 'secondary' : 'success'}
                    appearance="light"
                    data-testid="sql-line-preview-badge"
                  >
                    {previewBadgeText(linePreview.state.preview)}
                  </Badge>
                )}
              </div>
              <SqlPreviewGrid state={linePreview.state} />

              <div className="grid gap-4 md:grid-cols-2">
                <div className="flex min-w-0 flex-col gap-1.5">
                  <Label htmlFor="etl-from-date">
                    From date <span className="text-destructive">*</span>
                  </Label>
                  {editing ? (
                    <Input
                      id="etl-from-date"
                      type="date"
                      value={config.fromDate ?? ''}
                      onChange={(e) => onChange({ fromDate: e.target.value || null })}
                      aria-invalid={Boolean(fieldErrors.fromDate)}
                    />
                  ) : (
                    <span className="text-sm">{config.fromDate ?? '-'}</span>
                  )}
                  {fieldErrors.fromDate && (
                    <p className="text-xs text-destructive">{fieldErrors.fromDate}</p>
                  )}
                </div>
                <div className="flex min-w-0 flex-col gap-1.5">
                  <Label>
                    Document date column <span className="text-destructive">*</span>
                  </Label>
                  {editing ? (
                    <SearchSelect
                      options={docDateOptions}
                      value={config.docDateColumn ?? ''}
                      onChange={(v) => onChange({ docDateColumn: v || null })}
                      placeholder={pickersEnabled ? 'Pick a column' : 'Run Test query first'}
                      disabled={!pickersEnabled}
                      ariaLabel="Document date column"
                    />
                  ) : (
                    <ColumnChips values={config.docDateColumn ? [config.docDateColumn] : []} empty="-" />
                  )}
                  {fieldErrors.docDateColumn && (
                    <p className="text-xs text-destructive">{fieldErrors.docDateColumn}</p>
                  )}
                </div>
              </div>

              {/* The family filter (AC-02-11/19/20) - authored ONLY through the
                  formula builder, same dialog masters' Transform column uses
                  (Q16); the field itself shows the formula read-only. */}
              <div className="flex min-w-0 flex-col gap-1.5">
                <Label>Filter</Label>
                <div className="flex items-center gap-2">
                  {config.filterFormula ? (
                    <ClampedText
                      text={config.filterFormula}
                      lines={2}
                      className="flex-1 rounded-md border border-border bg-muted/30 px-3 py-2 font-mono text-xs"
                    />
                  ) : (
                    <span className="flex-1 rounded-md border border-dashed border-border px-3 py-2 text-xs text-muted-foreground">
                      Every header is staged (no filter).
                    </span>
                  )}
                  {editing && (
                    <Button
                      type="button"
                      variant="outline"
                      size="sm"
                      mode="icon"
                      onClick={() => setFilterBuilderOpen(true)}
                      aria-label="Build the filter formula"
                      title="Edit as a formula"
                    >
                      <Wand2 className="size-4" />
                    </Button>
                  )}
                </div>
                {fieldErrors.filterFormula && (
                  <p className="text-xs text-destructive">{fieldErrors.filterFormula}</p>
                )}
              </div>
            </div>
          )}

          {isDocument && (
            <AutocountFormulaBuilder
              open={filterBuilderOpen}
              onOpenChange={setFilterBuilderOpen}
              value={config.filterFormula ?? ''}
              onApply={(formula) => onChange({ filterFormula: formula.trim() ? formula.trim() : null })}
              onServerTest={onServerTest}
              variables={filterVariables}
              fieldLabel="Filter"
            />
          )}

          <SqlPreviewGrid state={preview.state} />

          <div className="grid gap-4 rounded-lg border border-border p-4 md:grid-cols-3">
            <div className="flex min-w-0 flex-col gap-1.5">
              <Label>
                Key columns <span className="text-destructive">*</span>
              </Label>
              {editing ? (
                <MultiSelect
                  options={keyColumnOptions}
                  value={config.keyColumns}
                  onChange={onKeyColumnsChange}
                  placeholder={pickersEnabled ? 'Pick columns' : 'Run Test query first'}
                  disabled={!pickersEnabled}
                  size="sm"
                />
              ) : (
                <ColumnChips values={config.keyColumns} empty="-" />
              )}
              {fieldErrors.keyColumns && (
                <p className="text-xs text-destructive">{fieldErrors.keyColumns}</p>
              )}
            </div>
            <div className="flex min-w-0 flex-col gap-1.5">
              <Label>Watermark column</Label>
              {editing ? (
                <SearchSelect
                  options={watermarkOptions}
                  value={config.watermarkColumn ?? NO_WATERMARK}
                  onChange={(v) => onChange({ watermarkColumn: v === NO_WATERMARK ? null : v })}
                  placeholder="None"
                  disabled={!pickersEnabled}
                  ariaLabel="Watermark column"
                />
              ) : (
                <ColumnChips
                  values={config.watermarkColumn ? [config.watermarkColumn] : []}
                  empty="None"
                />
              )}
              {fieldErrors.watermarkColumn && (
                <p className="text-xs text-destructive">{fieldErrors.watermarkColumn}</p>
              )}
            </div>
            <div className="flex min-w-0 flex-col gap-1.5">
              <Label>Compared columns</Label>
              {editing ? (
                <MultiSelect
                  options={comparedOptions}
                  value={config.comparedColumns}
                  onChange={(comparedColumns) => onChange({ comparedColumns })}
                  placeholder={pickersEnabled ? 'All except key columns' : 'Run Test query first'}
                  disabled={!pickersEnabled}
                  size="sm"
                />
              ) : (
                <ColumnChips values={config.comparedColumns} empty="All except key columns" />
              )}
              {fieldErrors.comparedColumns && (
                <p className="text-xs text-destructive">{fieldErrors.comparedColumns}</p>
              )}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
