'use client';

/**
 * Whole-mapping simulator (AC-16-30/31) - a mock AutoCount record in → the whole
 * Sorento record out, run through the REAL MappingEngine on the server. It sends
 * the CURRENT (possibly unsaved) editor rows so the operator previews their DRAFT
 * before a sync stages a broken batch. It writes NOTHING - a pure transform
 * preview, distinct from the slice-14 Sorento dry-run (which asks Sorento what a
 * push would do). Failing fields are shown with their per-field error, never
 * silently omitted.
 */
import { useEffect, useMemo, useState } from 'react';
import { ArrowRight, LoaderCircle, Play, TriangleAlert } from 'lucide-react';
import { type ColumnDef, getCoreRowModel, useReactTable } from '@tanstack/react-table';
import {
  Dialog,
  DialogBody,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import { Button } from '@/components/ui/button';
import { Textarea } from '@/components/ui/textarea';
import { Badge } from '@/components/ui/badge';
import {
  Alert,
  AlertDescription,
  AlertIcon,
  AlertTitle,
} from '@/components/ui/alert';
import { SearchSelect } from '@/components/platform/search-select';
import { DataGrid } from '@/components/ui/data-grid';
import { DataGridTable } from '@/components/ui/data-grid-table';
import { cn } from '@/lib/utils';
import { humanizeFieldKey } from '@/lib/autocount-diff';
import type {
  AutocountMappingWriteRow,
  AutocountSimulateFieldResult,
  AutocountSimulateResult,
} from '@/types/autocount';

export interface MappingSimulatorProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  /** The CURRENT draft deliverable rows - sent so unsaved edits preview. */
  rows: AutocountMappingWriteRow[];
  /** Run the whole mapping over the mock record (writes nothing). `lines`
   *  (sprint-5/02) - a document's fetched line records for the picked
   *  header. */
  onSimulate: (
    record: Record<string, unknown>,
    rows: AutocountMappingWriteRow[],
    lines?: Array<Record<string, unknown>>,
  ) => Promise<AutocountSimulateResult>;
  entityLabel?: string;
  /**
   * Document entities only (sprint-5/02, AC-02-22) - the header query's LAST
   * `Test query` preview rows. Presence switches the dialog into document
   * mode: pick a real header (never hand-type JSON) by its key columns,
   * fetch its lines, then simulate header + lines + aggregates + status.
   * Undefined/empty = the master-entity free-JSON record editor (unchanged).
   */
  headerPreviewRows?: Array<Record<string, unknown>>;
  /** The header query's key columns - the picker's label + the value bound
   *  as `:doc_key` when fetching lines. */
  headerKeyColumns?: string[];
  /** Fetch the picked header's lines (re-runs the line query bound to its
   *  key). Required alongside `headerPreviewRows`. */
  onFetchLines?: (docKey: string) => Promise<Array<Record<string, unknown>>>;
}

/** A flat starting skeleton from the top-level (non-dotted) source paths, so the
 *  operator has a shape to edit rather than a blank object. */
function buildSkeleton(rows: AutocountMappingWriteRow[]): string {
  const obj: Record<string, string> = {};
  for (const r of rows) {
    if (r.sourcePath && !r.sourcePath.includes('.')) obj[r.sourcePath] = '';
  }
  return JSON.stringify(obj, null, 2);
}

function renderValue(value: unknown): string {
  if (value === null || value === undefined) return '-';
  if (typeof value === 'string') return value === '' ? '""' : value;
  return String(value);
}

/** AC-DLA-56 (T7) - flat, keyed field-result rows (columns below), migrated
 *  off the raw <table> onto DataGrid + DataGridTable. */
interface FieldResultRow {
  id: string;
  field: AutocountSimulateFieldResult;
}

function fieldResultRows(result: AutocountSimulateResult): FieldResultRow[] {
  return [
    ...result.headerFields.map((f) => ({
      id: `h-${f.canonicalField}-${f.sourcePath}`,
      field: f,
    })),
    ...result.lineFields.flatMap((line, li) =>
      line.map((f) => ({ id: `l-${li}-${f.canonicalField}-${f.sourcePath}`, field: f })),
    ),
  ];
}

/** A header preview row's picker label - its key column values joined. */
function headerRowLabel(row: Record<string, unknown>, keyColumns: string[]): string {
  const parts = keyColumns.map((k) => String(row[k] ?? ''));
  return parts.filter(Boolean).join(' · ') || '(blank key)';
}

export function MappingSimulator({
  open,
  onOpenChange,
  rows,
  onSimulate,
  entityLabel,
  headerPreviewRows,
  headerKeyColumns = [],
  onFetchLines,
}: MappingSimulatorProps) {
  const isDocumentMode = Boolean(headerPreviewRows && headerPreviewRows.length > 0 && onFetchLines);
  const [recordText, setRecordText] = useState('');
  const [selectedIndex, setSelectedIndex] = useState('');
  const [result, setResult] = useState<AutocountSimulateResult | null>(null);
  const [running, setRunning] = useState(false);
  const [runError, setRunError] = useState<string | null>(null);

  useEffect(() => {
    if (open) {
      setRecordText(isDocumentMode ? '' : buildSkeleton(rows));
      setSelectedIndex('');
      setResult(null);
      setRunError(null);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open]);

  const headerOptions = useMemo(
    () =>
      (headerPreviewRows ?? []).map((row, index) => ({
        label: headerRowLabel(row, headerKeyColumns),
        value: String(index),
      })),
    [headerPreviewRows, headerKeyColumns],
  );

  const selectedHeader = useMemo(() => {
    if (!isDocumentMode || selectedIndex === '') return null;
    return headerPreviewRows?.[Number(selectedIndex)] ?? null;
  }, [headerPreviewRows, isDocumentMode, selectedIndex]);

  useEffect(() => {
    if (selectedHeader) setRecordText(JSON.stringify(selectedHeader, null, 2));
  }, [selectedHeader]);

  const parsed = useMemo<
    { ok: true; record: Record<string, unknown> } | { ok: false; error: string }
  >(() => {
    if (recordText.trim() === '') {
      return {
        ok: false,
        error: isDocumentMode ? 'Pick a header row.' : 'Enter a mock AutoCount record.',
      };
    }
    try {
      const value = JSON.parse(recordText);
      if (value === null || typeof value !== 'object' || Array.isArray(value)) {
        return { ok: false, error: 'The record must be a JSON object.' };
      }
      return { ok: true, record: value as Record<string, unknown> };
    } catch {
      return { ok: false, error: 'That is not valid JSON.' };
    }
  }, [isDocumentMode, recordText]);

  const run = async () => {
    if (!parsed.ok) return;
    setRunning(true);
    setRunError(null);
    try {
      let lines: Array<Record<string, unknown>> | undefined;
      if (isDocumentMode && onFetchLines) {
        const docKey = headerKeyColumns.length > 0 ? String(parsed.record[headerKeyColumns[0]] ?? '') : '';
        lines = await onFetchLines(docKey);
      }
      const res = await onSimulate(parsed.record, rows, lines);
      setResult(res);
    } catch {
      setRunError('The simulation could not be run.');
      setResult(null);
    } finally {
      setRunning(false);
    }
  };

  const outputJson = result?.record ? JSON.stringify(result.record, null, 2) : null;
  const failedFields = result
    ? [...result.headerFields, ...result.lineFields.flat()].filter((f) => !f.ok)
    : [];

  const resultRows = useMemo(() => (result ? fieldResultRows(result) : []), [result]);
  const resultColumns = useMemo<ColumnDef<FieldResultRow>[]>(
    () => [
      {
        id: 'sorentoField',
        header: 'Sorento field',
        cell: ({ row }) => (
          <span className="font-medium">{humanizeFieldKey(row.original.field.canonicalField)}</span>
        ),
      },
      {
        id: 'source',
        header: 'Source',
        cell: ({ row }) => (
          <code className="text-xs text-muted-foreground">{row.original.field.sourcePath}</code>
        ),
      },
      {
        id: 'value',
        header: 'Value',
        cell: ({ row }) =>
          row.original.field.ok ? (
            <code className="text-xs">{renderValue(row.original.field.value)}</code>
          ) : (
            <span className="text-xs font-medium text-destructive">{row.original.field.error}</span>
          ),
      },
    ],
    [],
  );
  const resultTable = useReactTable({
    data: resultRows,
    columns: resultColumns,
    getRowId: (r) => r.id,
    getCoreRowModel: getCoreRowModel(),
  });

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-3xl">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            Simulate mapping
            {entityLabel && (
              <Badge variant="secondary" appearance="light" size="sm">
                {entityLabel}
              </Badge>
            )}
          </DialogTitle>
        </DialogHeader>

        <DialogBody className="flex flex-col gap-4">
          <p className="text-xs text-muted-foreground">
            {isDocumentMode
              ? 'Transforms a real header + its lines through the current mapping and writes nothing.'
              : 'Transforms a mock record through the current mapping and writes nothing - ' +
                'a preview of what a real sync would produce, not a Sorento push.'}
          </p>

          {isDocumentMode && (
            <div className="flex flex-col gap-1.5">
              <span className="text-xs font-medium text-muted-foreground">Header</span>
              <SearchSelect
                options={headerOptions}
                value={selectedIndex}
                onChange={setSelectedIndex}
                placeholder="Pick a header row"
                searchPlaceholder="Search headers"
                ariaLabel="Header row"
              />
            </div>
          )}

          <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
            <div className="flex flex-col gap-2">
              <span className="text-xs font-medium text-muted-foreground">
                AutoCount record (in)
              </span>
              <Textarea
                variant="sm"
                className="min-h-48 font-mono"
                aria-label="Mock AutoCount record"
                value={recordText}
                onChange={(e) => setRecordText(e.target.value)}
                readOnly={isDocumentMode}
              />
              {!parsed.ok && recordText.trim() !== '' && (
                <p className="text-xs text-destructive" data-testid="record-parse-error">
                  {parsed.error}
                </p>
              )}
            </div>

            <div className="flex flex-col gap-2">
              <span className="text-xs font-medium text-muted-foreground">
                Sorento record (out)
              </span>
              <div
                className="min-h-48 overflow-auto rounded-md border border-border bg-muted/30 p-3"
                data-testid="sorento-output"
              >
                {result === null ? (
                  <p className="text-xs text-muted-foreground">Run to see the result.</p>
                ) : outputJson ? (
                  <pre className="whitespace-pre-wrap break-words font-mono text-xs">
                    {outputJson}
                  </pre>
                ) : (
                  <div className="flex items-center gap-1.5 text-xs font-medium text-destructive">
                    <TriangleAlert className="size-4" /> This record would be rejected.
                  </div>
                )}
              </div>
            </div>
          </div>

          <div className="flex items-center gap-3">
            <Button type="button" onClick={run} disabled={!parsed.ok || running}>
              {running ? (
                <LoaderCircle className="size-4 animate-spin" />
              ) : (
                <Play className="size-4" />
              )}
              Run simulation
            </Button>
            {runError && <span className="text-xs text-destructive">{runError}</span>}
          </div>

          {result && (
            <div className="flex flex-col gap-3">
              {result.status && (
                <div className="flex items-center gap-2 text-sm">
                  <span className="text-muted-foreground">Status</span>
                  <Badge variant="primary" appearance="light" data-testid="simulate-status">
                    {result.status}
                  </Badge>
                </div>
              )}
              {failedFields.length > 0 && (
                <Alert variant="destructive" appearance="light">
                  <AlertIcon>
                    <TriangleAlert />
                  </AlertIcon>
                  <AlertTitle>
                    {failedFields.length} field{failedFields.length === 1 ? '' : 's'} failed
                  </AlertTitle>
                  <AlertDescription>
                    A real sync of this record would reject on these fields.
                  </AlertDescription>
                </Alert>
              )}

              <div data-testid="field-results">
                <DataGrid table={resultTable} recordCount={resultRows.length}>
                  <DataGridTable />
                </DataGrid>
              </div>
              <div
                className={cn(
                  'flex items-center gap-1.5 text-xs',
                  result.ok ? 'text-success' : 'text-destructive',
                )}
              >
                <ArrowRight className="size-3.5" />
                {result.ok
                  ? 'This record maps cleanly.'
                  : 'This record would not be delivered as-is.'}
              </div>
            </div>
          )}
        </DialogBody>
      </DialogContent>
    </Dialog>
  );
}
