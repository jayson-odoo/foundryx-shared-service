'use client';

/**
 * AC-DLA-56 (T7) - the job detail's "Failed assets" table, migrated off the
 * raw @/components/ui/table primitive onto DataGrid + DataGridTable (sticky
 * header + resizable/movable columns free from DataGrid's own defaults,
 * AC-DLA-13). Its own file (not inlined in `page.tsx`, which may only
 * export `default`/`metadata` per Next's route-segment convention) so it is
 * unit-testable without the page's `use(params)` + polling machinery.
 */
import { useMemo } from 'react';
import { type ColumnDef, getCoreRowModel, useReactTable } from '@tanstack/react-table';
import { Card, CardContent, CardHeader, CardHeading, CardTitle } from '@/components/ui/card';
import { DataGrid } from '@/components/ui/data-grid';
import { DataGridTable } from '@/components/ui/data-grid-table';
import { ClampedText } from '@/components/platform/clamped-text';
import type { JobFailure } from '@/types/jobs';

export function FailedAssetsCard({ failures }: { failures: JobFailure[] }) {
  const columns = useMemo<ColumnDef<JobFailure>[]>(
    () => [
      {
        id: 'key',
        header: 'Key',
        cell: ({ row }) => <ClampedText text={row.original.key} lines={1} className="font-mono text-xs" />,
      },
      {
        id: 'reason',
        header: 'Reason',
        cell: ({ row }) => (
          <ClampedText text={row.original.reason} lines={2} className="text-destructive" />
        ),
      },
    ],
    [],
  );
  const table = useReactTable({
    data: failures,
    columns,
    getRowId: (_row, index) => String(index),
    getCoreRowModel: getCoreRowModel(),
  });

  return (
    <Card className="mt-5">
      <CardHeader>
        <CardHeading>
          <CardTitle>Failed assets ({failures.length})</CardTitle>
        </CardHeading>
      </CardHeader>
      <CardContent className="p-0">
        <DataGrid table={table} recordCount={failures.length}>
          <DataGridTable />
        </DataGrid>
      </CardContent>
    </Card>
  );
}
