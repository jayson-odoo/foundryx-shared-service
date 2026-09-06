'use client';

import { useMemo } from 'react';
import { type ColumnDef, getCoreRowModel, useReactTable } from '@tanstack/react-table';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { DataGrid } from '@/components/ui/data-grid';
import { DataGridTable } from '@/components/ui/data-grid-table';
import { SearchSelect } from '@/components/platform/search-select';
import { useOmnichannelReport } from '@/hooks/use-omnichannel-report';
import { formatDuration } from '@/lib/duration';
import type { DurationByUserRow, DurationStats, ReportFilters, ResponseBucketRow } from '@/types/omnichannel';
import { DurationStatCard } from '../../components/duration-stat-card';
import { ReportLoadingCard } from './report-loading-card';

const BUCKET_COLUMNS: ColumnDef<ResponseBucketRow>[] = [
  { id: 'label', header: 'Response time', accessorFn: (r) => r.label, cell: ({ row }) => <span className="font-medium">{row.original.label}</span> },
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
 * Responses report (plan 30, AC-RPT-19/20/44) - median/p90/average totals
 * (`DurationStatCard`) plus the 7-bucket response-time distribution as a
 * `DataGrid` (AC-DLA-56 - every product table is a DataGrid, never a raw
 * `<table>`), or per-agent rows when grouped by user.
 */
export interface ResponsesReportProps {
  workspaceId: string;
  /** Already carries the effective `groupBy` (owned by `useReportFilters`). */
  filters: ReportFilters;
  /** `null` = the ungrouped distribution. */
  groupBy: string | null;
  onGroupByChange: (value: string | null) => void;
}

export function ResponsesReport({ workspaceId, filters, groupBy, onGroupByChange }: ResponsesReportProps) {
  const { report, loading, error } = useOmnichannelReport(workspaceId, 'responses', filters);

  const grouped = groupBy === 'user';
  const bucketRows = (grouped ? undefined : (report?.rows as ResponseBucketRow[] | undefined)) ?? [];
  const userRows = (grouped ? (report?.rows as DurationByUserRow[] | undefined) : undefined) ?? [];

  const bucketTable = useReactTable({ data: bucketRows, columns: BUCKET_COLUMNS, getRowId: (r) => r.bucket, getCoreRowModel: getCoreRowModel() });
  const userTable = useReactTable({ data: userRows, columns: USER_COLUMNS, getRowId: (r) => r.userId, getCoreRowModel: getCoreRowModel() });

  const groupByOptions = useMemo(
    () => [
      { label: 'By duration', value: 'none' },
      { label: 'By agent', value: 'user' },
    ],
    [],
  );

  if (loading || !report) return <ReportLoadingCard />;
  if (error) return <ReportLoadingCard errored />;

  return (
    <div className="flex flex-col gap-4">
      <DurationStatCard title="First response time" stats={report.totals as DurationStats} />
      <Card>
        <CardHeader className="flex-wrap gap-3">
          <CardTitle>Response time breakdown</CardTitle>
          <SearchSelect
            ariaLabel="Group by"
            className="w-40"
            value={groupBy ?? 'none'}
            onChange={(v) => onGroupByChange(v === 'none' ? null : v)}
            options={groupByOptions}
          />
        </CardHeader>
        <CardContent className="p-0">
          {grouped ? (
            <DataGrid table={userTable} recordCount={userRows.length} emptyMessage="No data in this range.">
              <DataGridTable />
            </DataGrid>
          ) : (
            <DataGrid table={bucketTable} recordCount={bucketRows.length} emptyMessage="No data in this range.">
              <DataGridTable />
            </DataGrid>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
