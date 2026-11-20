'use client';

/**
 * AC-DLA-56 (T7) - the import job's "Rows needing attention" error list,
 * migrated off the raw @/components/ui/table primitive onto DataGrid +
 * DataGridTable (sticky header + resizable/movable columns free from
 * DataGrid's own defaults, AC-DLA-13). Its own file (page.tsx may only
 * export default/metadata per Next's route-segment convention, and this
 * keeps useReactTable out of the page's early-return Rules-of-Hooks
 * ordering) - also makes it directly unit-testable.
 */
import { useMemo } from 'react';
import { type ColumnDef, getCoreRowModel, useReactTable } from '@tanstack/react-table';
import { DataGrid } from '@/components/ui/data-grid';
import { DataGridTable } from '@/components/ui/data-grid-table';
import type { ImportError } from '@/types/import';

export function ImportErrorsTable({ errors }: { errors: ImportError[] }) {
  const columns = useMemo<ColumnDef<ImportError>[]>(
    () => [
      {
        id: 'row',
        header: 'Row',
        accessorKey: 'row',
        size: 80,
      },
      {
        id: 'column',
        header: 'Column',
        cell: ({ row }) => <span className="font-mono text-xs">{row.original.column}</span>,
        size: 160,
      },
      {
        id: 'message',
        header: 'Problem',
        cell: ({ row }) => <span className="text-destructive">{row.original.message}</span>,
      },
    ],
    [],
  );
  const table = useReactTable({
    data: errors,
    columns,
    getRowId: (_row, index) => String(index),
    getCoreRowModel: getCoreRowModel(),
  });

  return (
    <div className="rounded-lg border">
      <DataGrid table={table} recordCount={errors.length}>
        <DataGridTable />
      </DataGrid>
    </div>
  );
}
