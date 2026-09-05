'use client';

import { useMemo } from 'react';
import { useRouter } from 'next/navigation';
import type { ColumnDef } from '@tanstack/react-table';
import { DataGridColumnHeader } from '@/components/ui/data-grid-column-header';
import { DataGridTableRowSelect, DataGridTableRowSelectAll } from '@/components/ui/data-grid-table';
import { Badge } from '@/components/ui/badge';
import { StatusBadge } from '@/components/platform/status-badge';
import { ClampedText } from '@/components/platform/clamped-text';
import { OverflowPills } from '@/components/platform/overflow-pills';
import type { ResourceListConfig } from '@/components/platform/resource-list';
import { useDatetime } from '@/hooks/use-datetime';
import { broadcastService } from '@/services/broadcast-service';
import type { Broadcast } from '@/types/omnichannel';
import type { FilterFieldDef, ListQuery } from '@/types/resource';
import { BROADCAST_STATUS_REGISTRY, BROADCAST_STATUS_SEGMENTS } from './broadcast-status';
import { useBroadcastActions } from './use-broadcast-actions';
import { broadcastFormPath, broadcastNewPath } from './paths';

const stop = (e: React.MouseEvent) => e.stopPropagation();

const FILTER_FIELDS: FilterFieldDef[] = [
  { field: 'name', label: 'Name', type: 'text' },
  { field: 'channel', label: 'Channel', type: 'text' },
  { field: 'scheduledAt', label: 'Scheduled / Sent at', type: 'date' },
  { field: 'createdAt', label: 'Created', type: 'date' },
  { field: 'createdBy', label: 'Created by', type: 'text' },
];

export function useBroadcastsListConfig(workspaceId: string | null): ResourceListConfig<Broadcast> {
  const { formatDateTime, formatDate } = useDatetime();
  const actions = useBroadcastActions(workspaceId);
  const router = useRouter();

  return useMemo<ResourceListConfig<Broadcast>>(() => {
    const columns: ColumnDef<Broadcast>[] = [
      {
        id: 'select',
        meta: { reorderable: false },
        header: () => (
          <div onClick={stop}>
            <DataGridTableRowSelectAll />
          </div>
        ),
        cell: ({ row }) => (
          <div onClick={stop}>
            <DataGridTableRowSelect row={row} />
          </div>
        ),
        size: 48,
        enableSorting: false,
        enableHiding: false,
        enableResizing: false,
      },
      {
        id: 'name',
        accessorFn: (row) => row.name,
        meta: { headerTitle: 'Name' },
        header: ({ column }) => <DataGridColumnHeader title="Name" column={column} />,
        cell: ({ row }) => <ClampedText text={row.original.name} lines={1} className="font-medium text-foreground" />,
        size: 220,
        enableSorting: true,
      },
      {
        id: 'labels',
        accessorFn: (row) => row.labels.join(', '),
        meta: { headerTitle: 'Labels' },
        header: ({ column }) => <DataGridColumnHeader title="Labels" column={column} />,
        cell: ({ row }) => (
          <OverflowPills
            items={row.original.labels}
            keyFor={(l) => l}
            renderPill={(l) => (
              <Badge size="sm" variant="secondary" appearance="light">
                {l}
              </Badge>
            )}
          />
        ),
        size: 160,
        enableSorting: false,
      },
      {
        id: 'channel',
        accessorFn: (row) => row.channelName,
        meta: { headerTitle: 'Channel' },
        header: ({ column }) => <DataGridColumnHeader title="Channel" column={column} />,
        cell: ({ row }) => <ClampedText text={row.original.channelName} lines={1} />,
        size: 160,
        enableSorting: true,
      },
      {
        id: 'audience',
        accessorFn: (row) =>
          row.audience.kind === 'segment'
            ? (row.audience.segmentName ?? 'Segment')
            : row.audience.kind === 'filter'
              ? 'Custom filter'
              : `${row.audience.contactIds?.length ?? 0} contacts`,
        meta: { headerTitle: 'Audience' },
        header: ({ column }) => <DataGridColumnHeader title="Audience" column={column} />,
        cell: ({ row }) => {
          const a = row.original.audience;
          const label = a.kind === 'segment' ? (a.segmentName ?? 'Segment') : a.kind === 'filter' ? 'Custom filter' : `${a.contactIds?.length ?? 0} contacts`;
          return <ClampedText text={label} lines={1} className="text-muted-foreground" />;
        },
        size: 160,
        enableSorting: false,
      },
      {
        id: 'recipients',
        accessorFn: (row) => row.counts.total,
        meta: { headerTitle: 'Recipients' },
        header: ({ column }) => <DataGridColumnHeader title="Recipients" column={column} />,
        cell: ({ row }) => <span>{row.original.counts.total}</span>,
        size: 110,
        enableSorting: true,
      },
      {
        id: 'status',
        accessorFn: (row) => row.status,
        meta: { headerTitle: 'Status' },
        header: ({ column }) => <DataGridColumnHeader title="Status" column={column} />,
        cell: ({ row }) => <StatusBadge status={row.original.status} registry={BROADCAST_STATUS_REGISTRY} />,
        size: 120,
        enableSorting: true,
      },
      {
        id: 'scheduledAt',
        accessorFn: (row) => row.scheduledAt ?? row.finishedAt ?? row.startedAt,
        meta: { headerTitle: 'Scheduled / Sent at' },
        header: ({ column }) => <DataGridColumnHeader title="Scheduled / Sent at" column={column} />,
        cell: ({ row }) => {
          const r = row.original;
          const when = r.scheduledAt ?? r.finishedAt ?? r.startedAt;
          return <span className="text-muted-foreground">{when ? formatDateTime(when) : '-'}</span>;
        },
        size: 170,
        enableSorting: true,
      },
      {
        id: 'counts',
        accessorFn: (row) => `${row.counts.sent}/${row.counts.delivered}/${row.counts.read}/${row.counts.failed}`,
        meta: { headerTitle: 'Sent / Delivered / Read / Failed' },
        header: ({ column }) => <DataGridColumnHeader title="Sent / Delivered / Read / Failed" column={column} />,
        cell: ({ row }) => {
          const c = row.original.counts;
          return (
            <span className="text-muted-foreground">
              {c.sent} / {c.delivered} / {c.read} / {c.failed}
            </span>
          );
        },
        size: 200,
        enableSorting: false,
      },
      {
        id: 'createdBy',
        accessorFn: (row) => row.createdByName ?? '-',
        meta: { headerTitle: 'Created by' },
        header: ({ column }) => <DataGridColumnHeader title="Created by" column={column} />,
        cell: ({ row }) => <ClampedText text={row.original.createdByName ?? '-'} lines={1} />,
        size: 150,
        enableSorting: false,
      },
      {
        id: 'createdAt',
        accessorFn: (row) => row.createdAt,
        meta: { headerTitle: 'Created' },
        header: ({ column }) => <DataGridColumnHeader title="Created" column={column} />,
        cell: ({ row }) => <span className="text-muted-foreground">{formatDate(row.original.createdAt)}</span>,
        size: 130,
        enableSorting: true,
      },
    ];

    return {
      viewKey: 'omnichannel.broadcasts.list',
      columns,
      getRowId: (row) => row.id,
      rowHref: (row) => broadcastFormPath(row.id),
      fetcher: (query: ListQuery) => {
        if (!workspaceId) return Promise.resolve({ data: [], total: 0, page: query.page });
        return broadcastService.list(workspaceId, query);
      },
      filterFields: FILTER_FIELDS,
      exportColumns: [],
      actions,
      searchPlaceholder: 'Search broadcasts…',
      searchHints: ['Name'],
      defaultSort: { id: 'createdAt', desc: true },
      enableStatusViews: false,
      segments: BROADCAST_STATUS_SEGMENTS,
      defaultSegment: 'all',
      createLabel: 'New broadcast',
      onCreate: () => router.push(broadcastNewPath),
      createPermission: 'broadcasts.manage',
    };
  }, [actions, workspaceId, formatDateTime, formatDate, router]);
}
