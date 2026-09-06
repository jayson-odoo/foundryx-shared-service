'use client';

import { useMemo, useState } from 'react';
import { type ColumnDef, getCoreRowModel, useReactTable } from '@tanstack/react-table';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { DataGrid } from '@/components/ui/data-grid';
import { DataGridTable } from '@/components/ui/data-grid-table';
import { SearchSelect } from '@/components/platform/search-select';
import { useOmnichannelReport } from '@/hooks/use-omnichannel-report';
import { formatDuration } from '@/lib/duration';
import type { CloseReasonRow, DurationByUserRow, DurationStats, ReportFilters } from '@/types/omnichannel';
import { DurationStatCard } from '../../components/duration-stat-card';
import { ReportLoadingCard } from './report-loading-card';

const REASON_COLUMNS: ColumnDef<CloseReasonRow>[] = [
  {
    id: 'name',
    header: 'Close reason',
    accessorFn: (r) => r.name ?? '',
    cell: ({ row }) => <span className="font-medium">{row.original.name ?? ''}</span>,
  },
  { id: 'count', header: 'Count', accessorFn: (r) => r.count },
  { id: 'percent', header: 'Percent', accessorFn: (r) => r.percent, cell: ({ row }) => `${row.original.percent}%` },
];

const USER_COLUMNS: ColumnDef<DurationByUserRow>[] = [
  { id: 'name', header: 'Agent', accessorFn: (r) => r.name, cell: ({ row }) => <span className="font-medium">{row.original.name}</span> },
  { id: 'sampleCount', header: 'Samples', accessorFn: (r) => r.sampleCount },
  { id: 'medianSeconds', header: 'Median', accessorFn: (r) => r.medianSeconds ?? -1, cell: ({ row }) => formatDuration(row.original.medianSeconds) },
  { id: 'p90Seconds', header: 'P90', accessorFn: (r) => r.p90Seconds ?? -1, cell: ({ row }) => formatDuration(row.original.p90Seconds) },
  { id: 'averageSeconds', header: 'Average', accessorFn: (r) => r.averageSeconds ?? -1, cell: ({ row }) => formatDuration(row.original.averageSeconds) },
];

/**
 * Resolutions report (plan 30, AC-RPT-21/22/44) - median/p90/average
 * resolution-time totals plus the close-reason breakdown (a `DataGrid`,
 * AC-DLA-56), or per-agent rows when grouped by user. A `null` close reason
 * renders empty (D-A9's "no invented label server-side" rule extends to the
 * client).
 */
export function ResolutionsReport({ workspaceId, filters }: { workspaceId: string; filters: ReportFilters }) {
  const [groupBy, setGroupBy] = useState<'none' | 'user'>('none');
  const { report, loading, error } = useOmnichannelReport(workspaceId, 'resolutions', {
    ...filters,
    groupBy: groupBy === 'user' ? 'user' : undefined,
  });

  const reasonRows = (groupBy === 'none' ? (report?.rows as CloseReasonRow[] | undefined) : undefined) ?? [];
  const userRows = (groupBy === 'user' ? (report?.rows as DurationByUserRow[] | undefined) : undefined) ?? [];

  const reasonTable = useReactTable({
    data: reasonRows,
    columns: REASON_COLUMNS,
    getRowId: (r) => r.closeReasonId ?? 'none',
    getCoreRowModel: getCoreRowModel(),
  });
  const userTable = useReactTable({ data: userRows, columns: USER_COLUMNS, getRowId: (r) => r.userId, getCoreRowModel: getCoreRowModel() });

  const groupByOptions = useMemo(
    () => [
      { label: 'By close reason', value: 'none' },
      { label: 'By agent', value: 'user' },
    ],
    [],
  );

  if (loading || !report) return <ReportLoadingCard />;
  if (error) return <ReportLoadingCard errored />;

  return (
    <div className="flex flex-col gap-4">
      <DurationStatCard title="Resolution time" stats={report.totals as DurationStats} />
      <Card>
        <CardHeader className="flex-wrap gap-3">
          <CardTitle>Resolution breakdown</CardTitle>
          <SearchSelect
            ariaLabel="Group by"
            className="w-44"
            value={groupBy}
            onChange={(v) => setGroupBy(v as 'none' | 'user')}
            options={groupByOptions}
          />
        </CardHeader>
        <CardContent className="p-0">
          {groupBy === 'user' ? (
            <DataGrid table={userTable} recordCount={userRows.length} emptyMessage="No data in this range.">
              <DataGridTable />
            </DataGrid>
          ) : (
            <DataGrid table={reasonTable} recordCount={reasonRows.length} emptyMessage="No data in this range.">
              <DataGridTable />
            </DataGrid>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
