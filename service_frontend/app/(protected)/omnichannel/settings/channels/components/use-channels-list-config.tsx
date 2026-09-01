'use client';

import { useMemo } from 'react';
import type { ColumnDef } from '@tanstack/react-table';
import { MessageCircle } from 'lucide-react';
import { DataGridColumnHeader } from '@/components/ui/data-grid-column-header';
import {
  DataGridTableRowSelect,
  DataGridTableRowSelectAll,
} from '@/components/ui/data-grid-table';
import { StatusBadge } from '@/components/platform/status-badge';
import { ActionMenu } from '@/components/platform/resource-actions/action-menu';
import type { ResourceListConfig } from '@/components/platform/resource-list';
import { channelService } from '@/services/channel-service';
import { useDatetime } from '@/hooks/use-datetime';
import type { FilterFieldDef } from '@/types/resource';
import type { Channel } from '@/types/omnichannel';
import { CHANNEL_STATUS_REGISTRY, CHANNEL_TYPE_LABELS } from './channel-status';
import { useChannelActions } from './use-channel-actions';
import { channelFormPath } from './paths';

const stop = (e: React.MouseEvent) => e.stopPropagation();

const FILTER_FIELDS: FilterFieldDef[] = [
  { field: 'name', label: 'Name', type: 'text' },
  { field: 'displayPhoneNumber', label: 'Phone Number', type: 'text' },
  {
    field: 'channelType',
    label: 'Channel',
    type: 'enum',
    options: [{ label: 'WhatsApp', value: 'WHATSAPP' }],
  },
  {
    field: 'status',
    label: 'Status',
    type: 'enum',
    options: [
      { label: 'Active', value: 'ACTIVE' },
      { label: 'Pending', value: 'PENDING' },
      { label: 'Inactive', value: 'INACTIVE' },
      { label: 'Error', value: 'ERROR' },
    ],
  },
  { field: 'created', label: 'Connected', type: 'date' },
];

export interface UseChannelsListConfigOptions {
  /** Triggered by the list's "Connect channel" button - opens the wizard. */
  onConnect: () => void;
}

export function useChannelsListConfig({
  onConnect,
}: UseChannelsListConfigOptions): ResourceListConfig<Channel> {
  const { formatDate } = useDatetime();
  const actions = useChannelActions();

  return useMemo<ResourceListConfig<Channel>>(() => {
    const columns: ColumnDef<Channel>[] = [
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
        meta: { headerTitle: 'Channel' },
        header: ({ column }) => <DataGridColumnHeader title="Channel" column={column} />,
        cell: ({ row }) => {
          const c = row.original;
          return (
            <div className="flex items-center gap-2.5">
              <span className="flex size-8 items-center justify-center rounded-md bg-[#25D366]/10 text-[#25D366]">
                <MessageCircle className="size-4" />
              </span>
              <div className="flex flex-col">
                <span className="font-medium text-foreground leading-tight">{c.name}</span>
                <span className="text-xs text-muted-foreground">
                  {CHANNEL_TYPE_LABELS[c.channelType]}
                </span>
              </div>
            </div>
          );
        },
        size: 280,
        enableSorting: true,
      },
      {
        id: 'displayPhoneNumber',
        accessorFn: (row) => row.displayPhoneNumber,
        meta: { headerTitle: 'Phone Number' },
        header: ({ column }) => <DataGridColumnHeader title="Phone Number" column={column} />,
        cell: ({ row }) => (
          <span className="text-sm text-muted-foreground">
            {row.original.displayPhoneNumber ?? '-'}
          </span>
        ),
        size: 180,
        enableSorting: false,
      },
      {
        id: 'status',
        accessorFn: (row) => row.status,
        meta: { headerTitle: 'Status' },
        header: ({ column }) => <DataGridColumnHeader title="Status" column={column} />,
        cell: ({ row }) => (
          <StatusBadge status={row.original.status} registry={CHANNEL_STATUS_REGISTRY} />
        ),
        size: 130,
        enableSorting: true,
      },
      {
        id: 'created',
        accessorFn: (row) => row.createdAt,
        meta: { headerTitle: 'Connected' },
        header: ({ column }) => <DataGridColumnHeader title="Connected" column={column} />,
        cell: ({ row }) => (
          <span className="text-sm text-muted-foreground">{formatDate(row.original.createdAt)}</span>
        ),
        size: 150,
        enableSorting: true,
      },
      {
        id: 'actions',
        meta: { reorderable: false },
        header: () => null,
        cell: ({ row, table }) => {
          const meta = table.options.meta;
          const index = (meta?.pageStartIndex ?? 0) + row.index;
          return (
            <div onClick={stop} className="flex justify-end">
              <ActionMenu
                actions={actions}
                rows={[row.original]}
                runtime={{ ctx: meta?.resourceCtx, index, reload: meta?.reload ?? (() => {}) }}
                surface="row"
              />
            </div>
          );
        },
        size: 60,
        enableSorting: false,
        enableHiding: false,
        enableResizing: false,
      },
    ];

    return {
      viewKey: 'omnichannel.channels.list',
      columns,
      getRowId: (c) => c.id,
      rowHref: (c) => channelFormPath(c.id),
      fetcher: (q) => channelService.list(q),
      exporter: (q, cols, ids) => channelService.exportCsv(q, cols, ids),
      filterFields: FILTER_FIELDS,
      exportColumns: [
        { id: 'name', label: 'Channel' },
        { id: 'channelType', label: 'Type' },
        { id: 'phone', label: 'Phone Number' },
        { id: 'status', label: 'Status' },
        { id: 'created', label: 'Connected' },
      ],
      actions,
      searchPlaceholder: 'Search channels…',
      searchHints: ['Name', 'Phone Number'],
      defaultSort: { id: 'created', desc: true },
      enableStatusViews: true,
      exportFilename: 'channels',
      createLabel: 'Connect channel',
      createPermission: 'channels.manage',
      onCreate: onConnect,
    };
  }, [actions, onConnect, formatDate]);
}
