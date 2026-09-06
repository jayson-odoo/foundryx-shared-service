'use client';

import { useState } from 'react';
import { type ColumnDef, getCoreRowModel, useReactTable } from '@tanstack/react-table';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { DataGrid } from '@/components/ui/data-grid';
import { DataGridTable } from '@/components/ui/data-grid-table';
import { ReportChart } from '@/components/platform/report-chart';
import { SearchSelect } from '@/components/platform/search-select';
import { useOmnichannelReport } from '@/hooks/use-omnichannel-report';
import type { MessageChannelRow, MessagesReportTotals, ReportFilters } from '@/types/omnichannel';
import { ReportLoadingCard } from './report-loading-card';

const CHANNEL_COLUMNS: ColumnDef<MessageChannelRow>[] = [
  { id: 'name', header: 'Channel', accessorFn: (r) => r.name, cell: ({ row }) => <span className="font-medium">{row.original.name}</span> },
  { id: 'incoming', header: 'Incoming', accessorFn: (r) => r.incoming },
  { id: 'outgoing', header: 'Outgoing', accessorFn: (r) => r.outgoing },
];

/**
 * Messages report (plan 30, AC-RPT-23/44) - incoming vs outgoing series over
 * time, plus an optional per-channel breakdown (`DataGrid`, AC-DLA-56).
 */
export function MessagesReport({ workspaceId, filters }: { workspaceId: string; filters: ReportFilters }) {
  const [groupBy, setGroupBy] = useState<'none' | 'channel'>('none');
  const { report, loading, error } = useOmnichannelReport(workspaceId, 'messages', {
    ...filters,
    groupBy: groupBy === 'channel' ? 'channel' : undefined,
  });

  const channelRows = (groupBy === 'channel' ? (report?.rows as MessageChannelRow[] | undefined) : undefined) ?? [];
  const channelTable = useReactTable({
    data: channelRows,
    columns: CHANNEL_COLUMNS,
    getRowId: (r) => r.channelId,
    getCoreRowModel: getCoreRowModel(),
  });

  if (loading || !report) return <ReportLoadingCard />;
  if (error) return <ReportLoadingCard errored />;

  const totals = report.totals as MessagesReportTotals;

  return (
    <div className="flex flex-col gap-4">
      <Card>
        <CardContent className="flex flex-wrap gap-6 py-5">
          <div className="flex flex-col gap-1">
            <span className="text-xs text-muted-foreground">Incoming</span>
            <span className="text-xl font-heading font-semibold">{totals.incoming}</span>
          </div>
          <div className="flex flex-col gap-1">
            <span className="text-xs text-muted-foreground">Outgoing</span>
            <span className="text-xl font-heading font-semibold">{totals.outgoing}</span>
          </div>
        </CardContent>
      </Card>
      <Card>
        <CardHeader className="flex-wrap gap-3">
          <CardTitle>Messages over time</CardTitle>
          <SearchSelect
            ariaLabel="Group by"
            className="w-40"
            value={groupBy}
            onChange={(v) => setGroupBy(v as 'none' | 'channel')}
            options={[
              { label: 'Over time', value: 'none' },
              { label: 'By channel', value: 'channel' },
            ]}
          />
        </CardHeader>
        <CardContent className={groupBy === 'channel' ? 'p-0' : undefined}>
          {groupBy === 'channel' ? (
            <DataGrid table={channelTable} recordCount={channelRows.length} emptyMessage="No data in this range.">
              <DataGridTable />
            </DataGrid>
          ) : (
            <ReportChart buckets={report.buckets} series={report.series} className="h-72 w-full" />
          )}
        </CardContent>
      </Card>
    </div>
  );
}
