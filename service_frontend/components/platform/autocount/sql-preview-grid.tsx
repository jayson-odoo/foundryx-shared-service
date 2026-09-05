'use client';

import { LoaderCircleIcon, TriangleAlert } from 'lucide-react';
import { type ColumnDef, getCoreRowModel, useReactTable } from '@tanstack/react-table';
import { Alert, AlertIcon, AlertTitle } from '@/components/ui/alert';
import { DataGrid } from '@/components/ui/data-grid';
import { DataGridTable } from '@/components/ui/data-grid-table';
import { ClampedText } from '@/components/platform/clamped-text';
import type { SqlPreviewState } from '@/hooks/use-autocount-etl';
import type { AutocountSqlPreviewColumn } from '@/types/autocount';

export interface SqlPreviewGridProps {
  state: SqlPreviewState;
}

function cellText(value: unknown): string {
  if (value === null || value === undefined) return '';
  if (typeof value === 'object') return JSON.stringify(value);
  return String(value);
}

/**
 * The Test Query result grid (AC-22-06/07): column names + reported types in
 * the header, ≤ 100 rows, and every designed state - idle, loading, error
 * (sanitized), empty (0 rows still shows the columns) and success.
 *
 * AC-DLA-56 (T7): migrated off the raw <table> onto DataGrid + DataGridTable
 * (sticky header + resizable/movable columns free from DataGrid's own
 * defaults, AC-DLA-13) - dynamic columns built from the query's reported
 * column list (name + type stacked in the header). Hooks run unconditionally
 * ahead of the idle/loading/error early returns (Rules of Hooks) over an
 * empty columns/rows fallback when the state isn't 'success' yet.
 */
export function SqlPreviewGrid({ state }: SqlPreviewGridProps) {
  const previewColumns = state.status === 'success' ? state.preview.columns : [];
  const previewRows = state.status === 'success' ? state.preview.rows : [];

  // Columns rebuilt fresh each render (small, occasionally-run preview grid -
  // not worth memoizing; the dynamic shape comes straight off the query's
  // own reported column list).
  const columns: ColumnDef<Record<string, unknown>>[] = previewColumns.map(
    (col: AutocountSqlPreviewColumn) => ({
      id: col.name,
      header: () => (
        <span className="flex flex-col">
          <span className="text-foreground">{col.name}</span>
          <span className="font-mono text-2xs font-normal text-muted-foreground">{col.type}</span>
        </span>
      ),
      accessorFn: (row) => row[col.name],
      cell: ({ getValue }) => {
        const raw = getValue();
        const isNull = raw === null || raw === undefined;
        if (isNull) return <span className="font-mono text-muted-foreground/70">NULL</span>;
        return <ClampedText text={cellText(raw)} lines={1} />;
      },
      meta: typeof previewRows[0]?.[col.name] === 'number' ? { cellClassName: 'text-end tabular-nums' } : undefined,
    }),
  );

  const table = useReactTable({
    data: previewRows,
    columns,
    getRowId: (_row, index) => String(index),
    getCoreRowModel: getCoreRowModel(),
  });

  if (state.status === 'idle') {
    return (
      <div
        className="flex items-center justify-center rounded-lg border border-dashed border-border py-10 text-sm text-muted-foreground"
        data-testid="sql-preview-idle"
      >
        No preview yet.
      </div>
    );
  }

  if (state.status === 'loading') {
    return (
      <div
        className="flex items-center justify-center gap-2 rounded-lg border border-border py-10 text-sm text-muted-foreground"
        data-testid="sql-preview-loading"
      >
        <LoaderCircleIcon className="size-4 animate-spin" />
        Running query…
      </div>
    );
  }

  if (state.status === 'error') {
    return (
      <Alert variant="destructive" appearance="light" data-testid="sql-preview-error">
        <AlertIcon>
          <TriangleAlert />
        </AlertIcon>
        <AlertTitle>{state.message}</AlertTitle>
      </Alert>
    );
  }

  return (
    <div className="flex flex-col gap-2" data-testid="sql-preview-success">
      {/* Scrolls within a bounded height - 100 rows must never push the
          column pickers below the fold (side panels never stretch the page). */}
      <div className="max-h-[26rem] overflow-auto rounded-lg border border-border">
        <DataGrid table={table} recordCount={previewRows.length} emptyMessage="Query returned no rows.">
          <DataGridTable />
        </DataGrid>
      </div>
    </div>
  );
}
