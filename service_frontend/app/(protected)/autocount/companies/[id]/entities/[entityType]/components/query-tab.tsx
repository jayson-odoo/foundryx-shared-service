'use client';

import { useCallback, useMemo } from 'react';
import Link from 'next/link';
import { Play, TriangleAlert } from 'lucide-react';
import { Alert, AlertIcon, AlertTitle } from '@/components/ui/alert';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { MultiSelect } from '@/components/platform/multi-select';
import { SearchSelect } from '@/components/platform/search-select';
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
  AutocountSqlConnection,
} from '@/types/autocount';

export interface QueryTabProps {
  editing: boolean;
  entityType: string;
  config: AutocountEtlSourceConfig;
  onChange: (patch: Partial<AutocountEtlSourceConfig>) => void;
  connections: AutocountSqlConnection[];
  connectionsLoading: boolean;
  schema: UseAutocountSqlSchemaResult;
  preview: UseSqlPreviewResult;
  /** Per-field 422 errors from the last save (AC-22-11). */
  fieldErrors: Record<string, string>;
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
  schema,
  preview,
  fieldErrors,
}: QueryTabProps) {
  const isDocument = isDocumentEntity(entityType);
  const connection = connections.find((c) => c.id === config.connectionId) ?? null;
  const previewColumns = useMemo(
    () => (preview.state.status === 'success' ? preview.state.preview.columns.map((c) => c.name) : []),
    [preview.state],
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
  const watermarkOptions = useMemo(
    () => [{ label: 'None', value: NO_WATERMARK }, ...columnOptions],
    [columnOptions],
  );
  const pickersEnabled = editing && columnOptions.length > 0;

  const canTest = Boolean(config.connectionId) && config.query.trim().length > 0 &&
    preview.state.status !== 'loading';

  const onTest = useCallback(() => {
    if (!config.connectionId) return;
    void preview.run(config.connectionId, config.query);
  }, [config.connectionId, config.query, preview]);

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
    },
    [onChange, preview],
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
      {!connectionsLoading && connections.length === 0 && (
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
              <SearchSelect
                options={connectionOptions}
                value={config.connectionId}
                onChange={onConnectionChange}
                placeholder={connectionsLoading ? 'Loading…' : 'Select a connection'}
                disabled={!editing || connectionsLoading || connections.length === 0}
                ariaLabel="Connection"
              />
            </div>
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
            <div className="grid gap-4 md:grid-cols-[minmax(0,1fr)_12rem]">
              <div className="flex min-w-0 flex-col gap-1.5">
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
              <div className="flex flex-col gap-1.5">
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
            </div>
          )}

          <SqlPreviewGrid state={preview.state} />

          <div className="grid gap-4 rounded-lg border border-border p-4 md:grid-cols-3">
            <div className="flex min-w-0 flex-col gap-1.5">
              <Label>
                Key columns <span className="text-destructive">*</span>
              </Label>
              {editing ? (
                <MultiSelect
                  options={columnOptions}
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
